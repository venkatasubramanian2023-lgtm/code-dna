"""Contract tests: every storage backend must behave the same way.

They run against the in-memory stand-ins always. They run against the real databases
only when CODEDNA_TEST_REAL=1 (start them with `docker compose up -d`). The real run
WIPES the databases it connects to, so it is never enabled by default.
"""
import os

import pytest

from codedna.dna.classifier import route
from codedna.storage import HybridStore
from codedna.storage.backends import memory as mem


@pytest.fixture(params=["memory", "real"])
def backends(request):
    if request.param == "memory":
        return dict(mongo=mem.MemoryMongo(), neo4j=mem.MemoryNeo4j(),
                    cassandra=mem.MemoryCassandra(), redis=mem.MemoryRedis())
    if os.environ.get("CODEDNA_TEST_REAL") != "1":
        pytest.skip("set CODEDNA_TEST_REAL=1 to test the real databases (this wipes them)")
    from codedna.storage.backends.cassandra_store import CassandraStore
    from codedna.storage.backends.mongo import MongoStore
    from codedna.storage.backends.neo4j_store import Neo4jStore
    from codedna.storage.backends.redis_store import RedisStore
    b = dict(mongo=MongoStore(), neo4j=Neo4jStore(), cassandra=CassandraStore(), redis=RedisStore())
    for s in b.values():
        s.clear()
    return b


@pytest.fixture
def store(backends, dna_a, dna_b):
    s = HybridStore(**backends)
    s.ingest(dna_a)
    s.ingest(dna_b)
    return s


# ------------------------------------------------------------------ MongoDB
def test_mongo_roundtrip(store, dna_a):
    doc = store.mongo.get_repo("acme/sample")
    assert set(doc) == {"metadata", "readme", "config", "structure", "language_share"}
    assert doc["metadata"]["owner"] == "acme" and doc["readme"].startswith("# Sample")
    assert store.mongo.list_ids() == ["acme/other", "acme/sample"]
    assert len(store.mongo.code_docs("acme/sample")) == len(dna_a["code_docs"])


def test_mongo_fingerprints_and_search(store):
    fps = {f["repo_id"]: f for f in store.mongo.fingerprints()}
    assert set(fps) == {"acme/sample", "acme/other"}
    assert len(fps["acme/sample"]["raw_vectors"]["semantic"]) == 64
    assert store.mongo.search_readme("command line") == ["acme/other"]
    assert store.mongo.find_by_metadata(owner="acme") == ["acme/other", "acme/sample"]


def test_mongo_reingest_replaces(store, dna_a):
    store.ingest(dna_a)
    assert len(store.mongo.code_docs("acme/sample")) == len(dna_a["code_docs"])


# -------------------------------------------------------------------- Neo4j
def test_neo4j_dependency_graph(store, dna_a):
    assert store.neo4j.packages_of("acme/sample") == sorted(dna_a["packages"])
    assert "requests" in store.neo4j.shared_packages("acme/sample", "acme/other")
    assert store.neo4j.repos_using("requests") == ["acme/other", "acme/sample"]
    assert store.neo4j.repos_using("Click") == ["acme/other"]


def test_neo4j_similar_by_dependencies_is_jaccard(store, dna_a, dna_b):
    a, b = set(dna_a["packages"]), set(dna_b["packages"])
    expected = round(len(a & b) / len(a | b), 4)
    result = store.neo4j.similar_by_dependencies("acme/sample", 5)
    assert result == [{"repo": "acme/other", "score": expected}]


def test_neo4j_contributor_graph(store):
    assert store.neo4j.contributors_of("acme/sample") == [("alice", 2), ("bob", 1)]
    assert store.neo4j.shared_developers("acme/sample", "acme/other") == ["alice"]
    assert store.neo4j.repos_connected_by_developers("acme/sample") == [("acme/other", 1)]


def test_neo4j_call_graph(store):
    top = dict(store.neo4j.most_called("acme/sample"))
    assert top["helper"] >= 2          # called from run (twice) and main


# ---------------------------------------------------------------- Cassandra
def test_cassandra_wide_rows(store, dna_a):
    m = store.cassandra.metrics("acme/sample")
    assert m["total_loc"] == dna_a["metrics"]["total_loc"] and m["classes"] == 2
    s = store.cassandra.statistics("acme/sample")
    assert s["commits"] == 3 and s["total_commits"] == 3 and s["authors"] == 2
    assert set(store.cassandra.all_metrics()) == {"acme/sample", "acme/other"}
    assert store.cassandra.metrics("nope") == {}


def test_cassandra_time_series(store):
    evo = store.cassandra.evolution("acme/sample")
    assert [e["month"] for e in evo] == ["2024-01", "2024-03"]
    assert evo[0]["commits"] == 2
    jan = store.cassandra.commits_in_month("acme/sample", "2024-01")
    assert [c["author"] for c in jan] == ["bob", "alice"]       # newest first


def test_cassandra_reingest_does_not_duplicate(store, dna_a):
    store.ingest(dna_a)
    assert len(store.cassandra.commits_in_month("acme/sample", "2024-01")) == 2
    assert len(store.cassandra.evolution("acme/sample")) == 2


# -------------------------------------------------------------------- Redis
def test_redis_lookup_and_ids(store):
    assert store.redis.repo_ids() == ["acme/other", "acme/sample"]
    lk = store.lookup("acme/sample")
    assert lk["main_language"] == "Python" and lk["commits"] == 3
    assert store.lookup("missing") is None


def test_redis_cache_hits_and_misses(store):
    store.redis.clear_cache()
    assert store.redis.get("k") is None
    store.redis.set("k", {"a": 1})
    assert store.redis.get("k") == {"a": 1}
    assert (store.redis.hits, store.redis.misses) == (1, 1)
    store.redis.clear_cache()
    assert store.lookup("acme/sample") is not None        # lookups are not cache


# --------------------------------------------------- unified access layer
def test_ingest_returns_timing_per_database(backends, dna_a):
    timings = HybridStore(**backends).ingest(dna_a)
    assert set(timings) == {"mongodb", "neo4j", "cassandra", "redis"}


def test_get_repo_assembles_all_four_databases(store):
    r = store.get_repo("acme/sample")
    assert r["metadata"]["owner"] == "acme"                   # MongoDB
    assert r["metrics"]["classes"] == 2                       # Cassandra (wide row)
    assert [e["month"] for e in r["evolution"]] == ["2024-01", "2024-03"]   # Cassandra series
    assert "requests" in r["packages"]                        # Neo4j
    assert r["contributors"][0] == ["alice", 2]               # Neo4j
    assert store.get_repo("missing") == {}


def test_repeated_queries_are_served_from_redis(store):
    store.redis.clear_cache()
    first = store.similar("acme/sample", 1)
    second = store.similar("acme/sample", 1)
    assert first == second and first[0]["repo"] == "acme/other"
    assert (store.redis.hits, store.redis.misses) == (1, 1)


def test_compare_explains_the_score(store):
    r = store.compare("acme/sample", "acme/other")
    assert "requests" in r["shared_packages"] and r["shared_developers"] == ["alice"]
    assert set(r["per_group"]) == {"metrics", "language", "dependency", "structure", "evolution", "semantic"}
    assert store.compare("acme/other", "acme/sample") == r     # order does not matter


def test_reingest_invalidates_cache_and_corpus(store, dna_a):
    store.similar("acme/sample", 1)
    store.ingest(dna_a)
    store.redis.hits = store.redis.misses = 0
    store.similar("acme/sample", 1)
    assert store.redis.misses == 1                             # recomputed, not stale


def test_clear_all(store):
    store.clear_all()
    assert store.repo_ids() == [] and store.mongo.list_ids() == []


def test_route_covers_what_the_backends_read(dna_a):
    parts = route(dna_a)
    assert set(parts["cassandra"]) == {"metrics", "repo_statistics", "commit_history", "evolution_series"}
