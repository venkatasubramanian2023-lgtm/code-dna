import json

import pytest

from codedna import cli, config, pipeline
from codedna.collection import github
from codedna.storage import HybridStore
from codedna.storage.backends import memory as mem


@pytest.fixture
def blank_store():
    return HybridStore(mongo=mem.MemoryMongo(), neo4j=mem.MemoryNeo4j(),
                       cassandra=mem.MemoryCassandra(), redis=mem.MemoryRedis())


def test_read_repo_list_skips_blanks_and_comments(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("a/b\n\n# comment\n  c/d  \n")
    assert pipeline.read_repo_list(str(f)) == ["a/b", "c/d"]


def test_run_ingests_exports_and_survives_a_failure(blank_store, sample_repo, other_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_DIR", str(tmp_path / "clones"))
    sources = {"acme/sample": sample_repo, "acme/other": other_repo}

    def collect(name):
        if name == "bad/repo":
            raise RuntimeError("clone failed")
        return github.collect(name, source=sources[name])

    lines = []
    log = pipeline.run(["acme/sample", "bad/repo", "acme/other"], blank_store, fresh=True,
                       results_dir=str(tmp_path / "res"), progress=lines.append, collect=collect)
    assert [r["status"] for r in log] == ["ok", "failed", "ok"]
    assert "clone failed" in log[1]["error"] and any("FAILED" in l for l in lines)
    assert blank_store.repo_ids() == ["acme/other", "acme/sample"]
    res = tmp_path / "res"
    fps = json.loads((res / "fingerprints.json").read_text())
    assert {f["repo_id"] for f in fps} == {"acme/sample", "acme/other"}
    assert set(fps[0]["raw_vectors"]) == {"metrics", "language", "dependency", "structure",
                                          "evolution", "semantic"}
    assert "acme/sample" in json.loads((res / "readmes.json").read_text())
    ingest_log = json.loads((res / "ingest_log.json").read_text())
    assert ingest_log["rows"][0]["main_language"] == "Python" and ingest_log["rows"][0]["total_commits"] == 3


def test_parse_params_casts_numbers():
    assert cli._parse_params(["k=3", "t=2.5", "name=flask"]) == {"k": 3, "t": 2.5, "name": "flask"}
    with pytest.raises(SystemExit):
        cli._parse_params(["novalue"])


def test_mapping_command_prints_every_group(capsys):
    assert cli.main(["mapping"]) == 0
    out = capsys.readouterr().out
    assert "metrics              -> cassandra" in out and "call_graph" in out and "lookup" in out


def test_evaluate_command_end_to_end(tmp_path, capsys):
    import numpy as np
    from test_analysis import SIZES, make_dna, RNG
    import csv
    centres = {c: {g: RNG.normal(0, 1, SIZES[g]) for g in SIZES} for c in ("web", "cli")}
    dnas, rows = [], []
    for c in centres:
        for i in range(3):
            d = make_dna(f"{c}/r{i}", centres[c], packages=[c + "lib"])
            dnas.append({"repo_id": d["repo_id"], "packages": d["packages"], "raw_vectors": d["raw_vectors"]})
            rows.append((d["repo_id"], c))
    (tmp_path / "fingerprints.json").write_text(json.dumps(dnas))
    (tmp_path / "readmes.json").write_text(json.dumps({d["repo_id"]: d["repo_id"] for d in dnas}))
    with open(tmp_path / "labels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["repo", "category"])
        w.writerows(rows)
    assert cli.main(["evaluate", "--results", str(tmp_path), "--labels", str(tmp_path / "labels.csv")]) == 0
    assert "6 repositories, 2 categories" in capsys.readouterr().out
    assert (tmp_path / "similarity_eval.csv").exists()


def test_cli_reports_unreachable_databases_clearly(monkeypatch, capsys):
    monkeypatch.setattr(config, "ALLOW_FALLBACK", False)
    monkeypatch.setattr(config, "MONGO_URI", "mongodb://127.0.0.1:1")
    assert cli.main(["query", "by_language", "language=Python"]) == 2
    assert "docker compose up -d" in capsys.readouterr().err


def test_benchmark_command_is_registered():
    args = cli.build_parser().parse_args(["benchmark", "--limit", "5", "--repeats", "7"])
    assert args.func is cli.cmd_benchmark and args.limit == 5 and args.repeats == 7
