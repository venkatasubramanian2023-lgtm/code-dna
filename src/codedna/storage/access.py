"""Step 8: hybrid storage behind one interface (the unified data access layer).

The rest of the application talks to HybridStore only. It splits a Code DNA record with
dna.classifier.route(), writes each part to its database, and reads them back together.
"""
import time

from codedna import config
from codedna.analysis.similarity import Corpus
from codedna.dna.classifier import route


def _connect(real_cls, fallback_cls):
    """Connect to a real database; with CODEDNA_FALLBACK=1 use the in-memory stand-in instead."""
    try:
        return real_cls(), "real"
    except Exception as exc:     # connection refused, driver not installed, ...
        if not config.ALLOW_FALLBACK:
            raise RuntimeError(
                f"{real_cls.__name__} could not connect: {exc}. Start the databases with "
                f"'docker compose up -d', or set CODEDNA_FALLBACK=1 for tests only.") from exc
        return fallback_cls(), "in-memory stand-in"


class HybridStore:
    def __init__(self, mongo=None, neo4j=None, cassandra=None, redis=None):
        """Pass backends to use them directly (tests); otherwise connect to the real ones."""
        from codedna.storage.backends import memory as mem
        from codedna.storage.backends.cassandra_store import CassandraStore
        from codedna.storage.backends.mongo import MongoStore
        from codedna.storage.backends.neo4j_store import Neo4jStore
        from codedna.storage.backends.redis_store import RedisStore
        self.backends = {}
        for attr, given, real, fake in (("mongo", mongo, MongoStore, mem.MemoryMongo),
                                        ("neo4j", neo4j, Neo4jStore, mem.MemoryNeo4j),
                                        ("cassandra", cassandra, CassandraStore, mem.MemoryCassandra),
                                        ("redis", redis, RedisStore, mem.MemoryRedis)):
            if given is not None:
                store, mode = given, "provided"
            else:
                store, mode = _connect(real, fake)
            setattr(self, attr, store)
            self.backends[store.name] = mode
        self._corpus = None

    # ---------------------------------------------------------------- write path
    def ingest(self, dna: dict) -> dict:
        """Split one DNA record by data type, write each part to its database.
        Returns seconds spent per database."""
        repo_id = dna["repo_id"]
        parts = route(dna)
        fingerprint = {"repo_id": repo_id, "packages": dna["packages"], "raw_vectors": dna["raw_vectors"]}
        timings = {}

        def timed(name, fn, *args):
            t = time.perf_counter()
            fn(*args)
            timings[name] = round(time.perf_counter() - t, 4)

        timed("mongodb", self.mongo.save, repo_id, parts["mongodb"], fingerprint)
        timed("neo4j", self.neo4j.save, repo_id, parts["neo4j"])
        timed("cassandra", self.cassandra.save, repo_id, parts["cassandra"])
        timed("redis", self.redis.put_lookup, repo_id, parts["redis"]["lookup"])
        self._corpus = None
        self.redis.clear_cache()      # cached answers may be out of date once a repository changes
        return timings

    # ----------------------------------------------------------------- read path
    def repo_ids(self) -> list:
        return self.redis.repo_ids()

    def lookup(self, repo_id: str):
        """Fast summary from Redis (language, LOC, commits, contributors, packages)."""
        return self.redis.get_lookup(repo_id)

    def get_repo(self, repo_id: str) -> dict:
        """Everything known about one repository, assembled from all four databases."""
        key = f"repo:{repo_id}"
        hit = self.redis.get(key)
        if hit is not None:
            return hit
        doc = self.mongo.get_repo(repo_id)
        if not doc:
            return {}
        record = {"repo_id": repo_id, **doc,
                  "metrics": self.cassandra.metrics(repo_id),
                  "statistics": self.cassandra.statistics(repo_id),
                  "evolution": self.cassandra.evolution(repo_id),
                  "packages": self.neo4j.packages_of(repo_id),
                  "contributors": self.neo4j.contributors_of(repo_id, 10)}
        record["readme"] = (record.get("readme") or "")[:500]      # keep cached copies small
        record = _jsonable(record)
        self.redis.set(key, record)
        return record

    def corpus(self) -> Corpus:
        if self._corpus is None:
            docs = [{"repo_id": f["repo_id"], "packages": f["packages"], "raw_vectors": f["raw_vectors"]}
                    for f in self.mongo.fingerprints()]
            self._corpus = Corpus(sorted(docs, key=lambda d: d["repo_id"]))
        return self._corpus

    def similar(self, repo_id: str, k: int = 5) -> list:
        key = f"similar:{repo_id}:{k}"
        hit = self.redis.get(key)
        if hit is not None:
            return hit
        result = self.corpus().top_k(repo_id, k)
        self.redis.set(key, result)
        return result

    def compare(self, a: str, b: str) -> dict:
        """Similarity of two repositories, explained by group and by shared packages / developers."""
        key = "compare:" + ":".join(sorted([a, b]))
        hit = self.redis.get(key)
        if hit is not None:
            return hit
        result = self.corpus().similarity(a, b)
        result["shared_packages"] = self.neo4j.shared_packages(a, b)
        result["shared_developers"] = self.neo4j.shared_developers(a, b)
        self.redis.set(key, result)
        return result

    def clear_all(self):
        for store in (self.mongo, self.neo4j, self.cassandra, self.redis):
            store.clear()
        self._corpus = None


def _jsonable(obj):
    import json
    return json.loads(json.dumps(obj, default=str))
