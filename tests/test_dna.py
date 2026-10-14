import pytest

from codedna import config
from codedna.collection import github
from codedna.dna import choose_store, generate, mapping, route
from codedna.dna import vectors
from codedna.dna.classifier import Profile


@pytest.fixture(scope="module")
def dna(sample_repo, tmp_path_factory):
    """DNA of the sample repository, built through the real collector."""
    saved = config.REPO_DIR
    config.REPO_DIR = str(tmp_path_factory.mktemp("clones"))
    try:
        collected = github.collect("acme/sample", source=sample_repo)
    finally:
        config.REPO_DIR = saved
    return generate(collected)


def test_vector_sizes_match_schema(dna):
    v = dna["raw_vectors"]
    assert len(v["metrics"]) == config.DIM_METRICS
    assert len(v["language"]) == config.DIM_LANGUAGE
    assert len(v["dependency"]) == config.DIM_DEPENDENCY
    assert len(v["structure"]) == config.DIM_STRUCTURE
    assert len(v["evolution"]) == config.DIM_EVOLUTION
    assert len(v["semantic"]) == config.DIM_SEMANTIC


def test_generate_record_contents(dna):
    assert dna["repo_id"] == "acme/sample"
    assert dna["metadata"]["owner"] == "acme" and dna["metadata"]["name"] == "sample"
    assert dna["metadata"]["readme_length"] > 0
    assert {"requests", "numpy", "flask"} <= set(dna["packages"])
    assert dna["evolution_summary"]["commits"] == 3
    assert dna["author_counts"] == {"alice": 2, "bob": 1}


def test_dependency_vector_is_order_independent_and_deterministic():
    a = vectors.dependency_vector(["requests", "numpy", "flask"])
    b = vectors.dependency_vector(["flask", "requests", "numpy"])
    assert a == b
    assert vectors.dependency_vector([]) == [0.0] * config.DIM_DEPENDENCY
    assert a != vectors.dependency_vector(["django"])


def test_language_vector_order():
    v = vectors.language_vector({"Python": 0.75, "JavaScript": 0.25})
    assert v[0] == 0.75 and v[1] == 0.25 and sum(v) == 1.0


def test_bus_factor():
    assert vectors.bus_factor({"a": 90, "b": 5, "c": 5}) == 1
    assert vectors.bus_factor({"a": 10, "b": 10, "c": 10, "d": 10}) == 2


def test_choose_store_rule_order():
    assert choose_store(Profile(relational=True, wide_column=True)) == "neo4j"
    assert choose_store(Profile(wide_column=True, hot=True)) == "cassandra"
    assert choose_store(Profile(hot=True)) == "redis"
    assert choose_store(Profile()) == "mongodb"


def test_mapping_matches_schema_document():
    m = mapping()
    for g in ("metadata", "readme", "config", "code_docs", "structure", "language_share"):
        assert m[g] == "mongodb"
    for g in ("dependency_graph", "call_graph", "contributor_graph"):
        assert m[g] == "neo4j"
    for g in ("metrics", "repo_statistics", "commit_history", "evolution_series"):
        assert m[g] == "cassandra"
    for g in ("lookup", "similarity_cache", "repo_cache"):
        assert m[g] == "redis"


def test_route_sends_each_group_to_its_database(dna):
    parts = route(dna)
    assert set(parts["mongodb"]) == {"metadata", "readme", "config", "code_docs", "structure",
                                     "language_share"}
    assert set(parts["neo4j"]) == {"dependency_graph", "call_graph", "contributor_graph"}
    assert set(parts["cassandra"]) == {"metrics", "repo_statistics", "commit_history",
                                       "evolution_series"}
    assert set(parts["redis"]) == {"lookup"}
    routed = [k for p in parts.values() for k in p]
    assert len(routed) == len(set(routed)) == 14       # nothing lost or duplicated


def test_lookup_summary_is_compact(dna):
    lookup = route(dna)["redis"]["lookup"]
    assert lookup["repo_id"] == "acme/sample" and lookup["main_language"] == "Python"
    assert lookup["commits"] == 3 and lookup["contributors"] == 2


def test_metadata_has_branches_and_age(dna):
    md = dna["metadata"]
    assert md["branches"] >= 1 and md["total_commits"] == 3
    assert md["first_commit"].startswith("2024-01-10")
    assert md["age_days"] == 55                          # 10 Jan to 5 Mar 2024
    assert "readme" not in md                            # README is its own group


def test_semantic_vector_reflects_vocabulary(dna):
    a = vectors.semantic_vector(["http", "request", "client", "http"])
    b = vectors.semantic_vector(["http", "client", "request", "http"])
    c = vectors.semantic_vector(["tensor", "gradient", "model"])
    assert a == b and a != c
    assert vectors.semantic_vector([]) == [0.0] * config.DIM_SEMANTIC
    assert any(dna["raw_vectors"]["semantic"])
