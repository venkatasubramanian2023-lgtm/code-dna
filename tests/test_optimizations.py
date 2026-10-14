"""The speed-ups must never change results."""
import json
import multiprocessing
import os
import subprocess
import sys

import pytest

from codedna.collection import github
from codedna.extraction import code_features, extract_code_features

SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def test_parallel_extraction_equals_sequential(sample_repo):
    sequential = extract_code_features(sample_repo, workers=1)
    parallel = extract_code_features(sample_repo, workers=2, parallel_min_files=0)
    assert parallel == sequential


def test_parallel_extraction_equals_sequential_on_many_files(tmp_path):
    for i in range(40):
        (tmp_path / f"m{i}.py").write_text(f"import requests\n\ndef f{i}(x):\n    if x:\n        return f{(i + 1) % 40}(x)\n")
    assert extract_code_features(str(tmp_path), workers=3, parallel_min_files=0) == \
        extract_code_features(str(tmp_path), workers=1)


def test_no_pool_is_started_from_inside_a_worker(sample_repo, monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("a worker must not start another pool")
    monkeypatch.setattr(code_features, "ProcessPoolExecutor", Boom)
    monkeypatch.setattr(multiprocessing, "parent_process", lambda: object())     # pretend: inside a worker
    result = extract_code_features(sample_repo, workers=4, parallel_min_files=0)
    assert result["metrics"]["classes"] == 2


def test_pool_failure_falls_back_to_sequential(sample_repo, monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            raise OSError("cannot start processes")
    monkeypatch.setattr(code_features, "ProcessPoolExecutor", Broken)
    assert extract_code_features(sample_repo, workers=4, parallel_min_files=0) == \
        extract_code_features(sample_repo, workers=1)


def test_chunked_git_log_equals_single_read(sample_repo, tmp_path, monkeypatch):
    path = github.clone("acme/sample", str(tmp_path), source=sample_repo)
    single = github.read_commits(path, jobs=1)
    monkeypatch.setattr(github, "PARALLEL_MIN_COMMITS", 2)
    monkeypatch.setattr(github, "MIN_CHUNK", 1)
    chunked = github.read_commits(path, jobs=2)
    assert len(single) == 3 and chunked == single


def test_chunked_git_log_respects_the_limit(sample_repo, tmp_path, monkeypatch):
    path = github.clone("acme/sample", str(tmp_path), source=sample_repo)
    monkeypatch.setattr(github, "PARALLEL_MIN_COMMITS", 1)
    monkeypatch.setattr(github, "MIN_CHUNK", 1)
    assert [c["sha"] for c in github.read_commits(path, limit=2, jobs=2)] == \
        [c["sha"] for c in github.read_commits(path, limit=2, jobs=1)]


def test_non_ascii_text_is_read_as_utf8_whatever_the_machine_default(tmp_path):
    """Windows defaults to cp1252. Run a child Python whose default encoding is ASCII."""
    (tmp_path / "m.py").write_text("def caf\u00e9_menu():\n    return 'na\u00efve'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Na\u00efve caf\u00e9\n", encoding="utf-8")
    code = ("import sys, json; sys.path.insert(0, %r)\n"
            "from codedna.extraction import extract_code_features\n"
            "from codedna.collection import github\n"
            "f = extract_code_features(%r, workers=1)\n"
            "print(json.dumps([f['file_docs'][0]['functions'], github.read_readme(%r)], ensure_ascii=True))"
            % (SRC, str(tmp_path), str(tmp_path)))
    env = dict(os.environ, PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LC_ALL="C", LANG="C")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    functions, readme = json.loads(out.stdout)
    assert functions == ["caf\u00e9_menu"] and readme.startswith("# Na\u00efve caf\u00e9")
