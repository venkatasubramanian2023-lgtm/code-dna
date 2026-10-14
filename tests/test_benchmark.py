import json

import mongomock
import pytest

from codedna.benchmark import SingleStoreBaseline, run_benchmark
from codedna.benchmark import runner
from codedna.storage import HybridStore
from codedna.storage.backends import memory as mem


@pytest.fixture
def systems():
    hybrid = HybridStore(mongo=mem.MemoryMongo(), neo4j=mem.MemoryNeo4j(),
                         cassandra=mem.MemoryCassandra(), redis=mem.MemoryRedis())
    baseline = SingleStoreBaseline(mongomock.MongoClient()["baseline"])
    return hybrid, baseline


def test_both_systems_give_identical_answers(many_dnas, systems):
    hybrid, baseline = systems
    result = run_benchmark(many_dnas, hybrid, baseline, repeats=5, progress=lambda _: None)
    assert result["repositories"] == 6
    for query, a in result["agreement"].items():
        assert a["checked"] > 0 and a["identical"] == a["checked"], query


def test_latency_rows_and_routed_bytes(many_dnas, systems):
    hybrid, baseline = systems
    result = run_benchmark(many_dnas, hybrid, baseline, repeats=4, progress=lambda _: None)
    rows = {(r["query"], r["system"]): r for r in result["latency"]}
    assert len(rows) == 11
    assert ("similar_to (warm, Redis cache)", "hybrid") in rows and ("similar_to", "mongodb_only") in rows
    assert all(r["n"] == 4 and r["median_ms"] >= 0 and r["p95_ms"] >= r["median_ms"] for r in rows.values())
    shares = [v["share"] for v in result["routed_bytes"].values()]
    assert sum(shares) == pytest.approx(1.0, abs=0.001) and all(v["bytes"] > 0 for v in result["routed_bytes"].values())
    assert set(result["ingest"]["hybrid_by_database_s"]) == {"mongodb", "neo4j", "cassandra", "redis"}


def test_agreement_check_detects_a_wrong_baseline(many_dnas, systems, monkeypatch):
    hybrid, baseline = systems
    runner.ingest_all(many_dnas, hybrid, baseline)
    monkeypatch.setattr(baseline, "using_technology", lambda t: [])          # deliberately wrong
    agreement = runner.check_agreement(many_dnas, runner.QueryEngine(hybrid), baseline)
    a = agreement["using_technology"]
    assert a["identical"] < a["checked"]
    assert agreement["similar_to"]["identical"] == agreement["similar_to"]["checked"]


def test_baseline_queries_directly(many_dnas, systems):
    _, baseline = systems
    for d in many_dnas:
        baseline.ingest(d)
    assert baseline.using_technology("Flask") == ["lab/web1", "lab/web2"]
    assert baseline.repo_ids()[0] == "lab/cli1"
    top = baseline.similar_dependencies("lab/web1", 1)[0]
    assert top["repo"] == "lab/web2" and "flask" in top["shared_packages"]
    assert baseline.contributors_of("lab/web1")["connected_repositories"][0]["shared_developers"] == 1
    assert baseline.similar_to("lab/data1", 1)[0]["repo"] == "lab/data2"
    baseline.ingest(many_dnas[0])                                           # re-ingest replaces
    assert baseline.db.b_commits.count_documents({"repo_id": "lab/web1"}) == len(many_dnas[0]["commits"])
    baseline.clear()
    assert baseline.repo_ids() == []


def test_outputs_and_report(many_dnas, systems, tmp_path):
    hybrid, baseline = systems
    result = run_benchmark(many_dnas, hybrid, baseline, repeats=3, progress=lambda _: None)
    runner.write_outputs(result, str(tmp_path))
    assert json.loads((tmp_path / "benchmark.json").read_text())["repositories"] == 6
    assert (tmp_path / "benchmark.csv").read_text().startswith("query,system,n,median_ms")
    report = runner.format_report(result)
    assert "answers identical" in report and "mongodb_only" in report and "routed" in report
