import pytest

from codedna.query import QUERIES, QueryEngine, UnknownRepository


@pytest.fixture
def engine(memory_store):
    return QueryEngine(memory_store)


def test_similar_to(engine):
    r = engine.similar_to("acme/sample", k=1)
    assert r["results"][0]["repo"] == "acme/other"
    assert r["databases"] == ["mongodb", "redis"] and r["ms"] >= 0


def test_using_technology_is_case_insensitive(engine):
    assert engine.using_technology("Requests")["results"] == ["acme/other", "acme/sample"]
    assert engine.using_technology("click")["results"] == ["acme/other"]
    assert engine.using_technology("react")["results"] == []
    assert engine.using_technology("click")["databases"] == ["neo4j"]


def test_high_complexity_filters_and_sorts(engine, dna_a, dna_b):
    a, b = dna_a["metrics"]["avg_cyclomatic"], dna_b["metrics"]["avg_cyclomatic"]
    lo, hi = sorted([a, b])
    everything = engine.high_complexity(threshold=0)["results"]
    assert [r["avg_cyclomatic"] for r in everything] == sorted([a, b], reverse=True)
    above = engine.high_complexity(threshold=(lo + hi) / 2)["results"]
    assert len(above) == 1 and above[0]["avg_cyclomatic"] == hi
    assert engine.high_complexity(threshold=1000)["results"] == []
    assert engine.high_complexity(threshold=0)["databases"] == ["cassandra"]


def test_high_complexity_other_metric_and_validation(engine):
    r = engine.high_complexity(threshold=0, metric="total_loc", top=1)
    assert len(r["results"]) == 1 and "total_loc" in r["results"][0]
    with pytest.raises(ValueError):
        engine.high_complexity(metric="not_a_metric")


def test_similar_dependencies_lists_shared_packages(engine):
    r = engine.similar_dependencies("acme/sample")
    assert r["results"][0]["repo"] == "acme/other"
    assert "requests" in r["results"][0]["shared_packages"]


def test_contributors_of(engine):
    r = engine.contributors_of("acme/sample")["results"]
    assert r["contributors"] == [{"developer": "alice", "commits": 2}, {"developer": "bob", "commits": 1}]
    assert r["connected_repositories"] == [{"repo": "acme/other", "shared_developers": 1}]


def test_by_language_and_readme_search(engine):
    assert engine.by_language("python")["results"] == ["acme/other", "acme/sample"]
    assert engine.by_language("rust")["results"] == []
    assert engine.search_readme("command line")["results"] == ["acme/other"]


def test_unknown_repository_is_an_error(engine):
    for name in ("similar_to", "similar_dependencies", "contributors_of"):
        with pytest.raises(UnknownRepository):
            engine.run(name, repo_id="nope/none")


def test_run_dispatches_by_name(engine):
    assert engine.run("using_technology", technology="click")["query"] == "using_technology"
    with pytest.raises(ValueError):
        engine.run("drop_tables")
    assert set(QUERIES) == {"similar_to", "using_technology", "high_complexity",
                            "similar_dependencies", "contributors_of", "by_language", "search_readme"}
