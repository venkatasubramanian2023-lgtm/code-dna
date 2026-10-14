import pytest
from fastapi.testclient import TestClient

from codedna.api import create_app


@pytest.fixture
def client(memory_store):
    with TestClient(create_app(memory_store)) as c:
        yield c


def test_health_and_mapping(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["repositories"] == 2
    assert set(h["backends"]) == {"mongodb", "neo4j", "cassandra", "redis"}
    m = client.get("/mapping").json()
    assert m["metrics"] == "cassandra" and m["call_graph"] == "neo4j" and m["lookup"] == "redis"


def test_repo_endpoints(client):
    assert client.get("/repos").json() == ["acme/other", "acme/sample"]
    r = client.get("/repos/acme/sample").json()
    assert r["metadata"]["owner"] == "acme" and r["metrics"]["classes"] == 2
    assert client.get("/repos/acme/missing").status_code == 404


def test_similarity_endpoints(client):
    s = client.get("/repos/acme/sample/similar", params={"k": 1}).json()
    assert s["results"][0]["repo"] == "acme/other"
    c = client.get("/compare", params={"a": "acme/sample", "b": "acme/other"}).json()
    assert "requests" in c["shared_packages"] and "per_group" in c
    assert client.get("/compare", params={"a": "acme/sample", "b": "x/y"}).status_code == 404
    d = client.get("/repos/acme/sample/dependencies/similar").json()
    assert d["results"][0]["repo"] == "acme/other"


def test_query_endpoints(client):
    assert client.get("/query/technology", params={"name": "click"}).json()["results"] == ["acme/other"]
    c = client.get("/query/complexity", params={"threshold": 0}).json()
    assert len(c["results"]) == 2 and c["databases"] == ["cassandra"]
    assert client.get("/query/complexity", params={"metric": "bogus"}).status_code == 422
    assert "avg_cyclomatic" in client.get("/query/metrics").json()
    assert client.get("/query/language", params={"name": "Python"}).json()["results"] == \
        ["acme/other", "acme/sample"]
    assert client.get("/search", params={"text": "command line"}).json()["results"] == ["acme/other"]
    who = client.get("/repos/acme/sample/contributors").json()["results"]
    assert who["contributors"][0] == {"developer": "alice", "commits": 2}


def test_parameter_validation(client):
    assert client.get("/repos/acme/sample/similar", params={"k": 0}).status_code == 422
    assert client.get("/repos/acme/sample/similar", params={"k": 999}).status_code == 422
    assert client.get("/query/technology").status_code == 422       # name is required


def test_ingest_rejects_bad_repo_names(client):
    assert client.post("/ingest", json={"repo": "not a repo"}).status_code == 422
    assert client.post("/ingest", json={"repo": "../../etc/passwd"}).status_code == 422
    assert client.post("/ingest", json={}).status_code == 422


def test_ingest_endpoint_end_to_end(client, sample_repo, monkeypatch, tmp_path):
    from codedna import config, pipeline
    from codedna.collection import github
    monkeypatch.setattr(config, "REPO_DIR", str(tmp_path))
    original = pipeline.ingest_repo
    local = lambda name: github.collect(name, source=sample_repo)
    monkeypatch.setattr(pipeline, "ingest_repo", lambda name, store: original(name, store, collect=local))
    r = client.post("/ingest", json={"repo": "neworg/third"})
    assert r.status_code == 201 and set(r.json()["store_by_db_s"]) == {"mongodb", "neo4j", "cassandra", "redis"}
    assert "neworg/third" in client.get("/repos").json()
    assert client.get("/repos/neworg/third").status_code == 200


def test_ingest_failure_is_a_502(client, monkeypatch):
    from codedna import pipeline
    def boom(name, store):
        raise RuntimeError("clone failed")
    monkeypatch.setattr(pipeline, "ingest_repo", boom)
    assert client.post("/ingest", json={"repo": "a/b"}).status_code == 502
