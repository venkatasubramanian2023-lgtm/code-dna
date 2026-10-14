"""Shared test fixtures: a tiny git repository built on the fly (no network needed)."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

SAMPLE_APP = '''\
import os
import requests
import numpy as np
from flask import Flask
from . import sibling


class Base:
    def run(self):
        return helper()


class Child(Base):
    def run(self):
        if os.name == "nt":
            return 1
        for i in range(3):
            if i > 1:
                return helper()
        return 0


def helper():
    return np.zeros(3)


def main():
    Child().run()
    helper()
'''

SAMPLE_UTIL = '''\
import requests


def fetch(url):
    # a comment
    return requests.get(url)
'''


def _git(path, *args, env=None):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory):
    """A repository with 3 commits by 2 authors, Python and JS files, tests/docs/CI folders."""
    root = tmp_path_factory.mktemp("sample")
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / ".github").mkdir()
    (root / "pkg" / "app.py").write_text(SAMPLE_APP)
    (root / "pkg" / "util.py").write_text(SAMPLE_UTIL)
    (root / "web.js").write_text("// js\nconsole.log(1);\nconsole.log(2);\n")
    (root / "tests" / "test_app.py").write_text("def test_x():\n    assert True\n")
    (root / "docs" / "index.md").write_text("docs")
    (root / ".github" / "ci.yml").write_text("on: push")
    (root / "README.md").write_text("# Sample\nA tiny sample project about web requests.\n")
    (root / "requirements.txt").write_text("requests>=2.0  # http\nnumpy\nflask==3.0\n-e .\n")
    (root / "LICENSE").write_text("MIT")

    def commit(msg, author, date):
        env = dict(os.environ, GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL=f"{author}@x.com",
                   GIT_COMMITTER_NAME=author, GIT_COMMITTER_EMAIL=f"{author}@x.com",
                   GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        _git(root, "add", "-A", env=env)
        _git(root, "commit", "-m", msg, env=env)

    _git(root, "init", "-q")
    commit("first", "alice", "2024-01-10T10:00:00Z")
    (root / "pkg" / "util.py").write_text(SAMPLE_UTIL + "\n\ndef more():\n    return 1\n")
    commit("second", "bob", "2024-01-20T10:00:00Z")
    (root / "web.js").write_text("// js\nconsole.log(1);\n")
    commit("third", "alice", "2024-03-05T10:00:00Z")
    return str(root)


OTHER_APP = '''\
import click
import requests


@click.command()
def cli():
    print(helper())


def helper():
    return requests.get("http://x")
'''


@pytest.fixture(scope="session")
def other_repo(tmp_path_factory):
    """A second repository: shares the author alice and the package requests with sample_repo."""
    root = tmp_path_factory.mktemp("other")
    (root / "cli.py").write_text(OTHER_APP)
    (root / "cmd.py").write_text(OTHER_APP.replace("def helper", "def helper2"))
    (root / "README.md").write_text("# Other\nA command line client for web requests.\n")
    (root / "requirements.txt").write_text("click\nrequests\n")
    _git(root, "init", "-q")
    for i, (author, date) in enumerate((("alice", "2024-02-01T10:00:00Z"), ("carol", "2024-02-15T10:00:00Z"))):
        (root / "cli.py").write_text(OTHER_APP + f"\n# edit {i}\n")
        env = dict(os.environ, GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL=f"{author}@x.com",
                   GIT_COMMITTER_NAME=author, GIT_COMMITTER_EMAIL=f"{author}@x.com",
                   GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        _git(root, "add", "-A", env=env)
        _git(root, "commit", "-m", f"c{i}", env=env)
    return str(root)


def build_dna(full_name, source, clone_dir):
    """Collect a local repository through the real collector and generate its Code DNA."""
    from codedna import config
    from codedna.collection import github
    from codedna.dna import generate
    saved, config.REPO_DIR = config.REPO_DIR, str(clone_dir)
    try:
        return generate(github.collect(full_name, source=source))
    finally:
        config.REPO_DIR = saved


@pytest.fixture(scope="session")
def dna_a(sample_repo, tmp_path_factory):
    return build_dna("acme/sample", sample_repo, tmp_path_factory.mktemp("ca"))


@pytest.fixture(scope="session")
def dna_b(other_repo, tmp_path_factory):
    return build_dna("acme/other", other_repo, tmp_path_factory.mktemp("cb"))


@pytest.fixture
def memory_store(dna_a, dna_b):
    """A HybridStore on the in-memory backends holding the two sample repositories."""
    from codedna.storage import HybridStore
    from codedna.storage.backends import memory as mem
    s = HybridStore(mongo=mem.MemoryMongo(), neo4j=mem.MemoryNeo4j(),
                    cassandra=mem.MemoryCassandra(), redis=mem.MemoryRedis())
    s.ingest(dna_a)
    s.ingest(dna_b)
    return s


def make_tiny_repo(root, packages, authors, branches_per_file, readme):
    """A small Python repository: one file per author, with different amounts of branching."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text("\n".join(packages) + "\n")
    (root / "README.md").write_text(readme)
    _git(root, "init", "-q")
    for i, author in enumerate(authors):
        body = "\n".join(f"    if x > {j}:\n        x += {j}" for j in range(branches_per_file * (i + 1)))
        (root / f"mod{i}.py").write_text(f"import {packages[0].split('=')[0]}\n\n\ndef f{i}(x):\n{body}\n    return x\n")
        env = dict(os.environ, GIT_AUTHOR_NAME=author, GIT_AUTHOR_EMAIL=f"{author}@x.com",
                   GIT_COMMITTER_NAME=author, GIT_COMMITTER_EMAIL=f"{author}@x.com",
                   GIT_AUTHOR_DATE=f"2024-0{1 + i % 9}-10T10:00:00Z", GIT_COMMITTER_DATE=f"2024-0{1 + i % 9}-10T10:00:00Z")
        _git(root, "add", "-A", env=env)
        _git(root, "commit", "-m", f"c{i}", env=env)
    return str(root)


@pytest.fixture(scope="session")
def many_dnas(tmp_path_factory):
    """Six repositories with overlapping packages and authors and different complexity."""
    specs = [
        ("lab/web1", ["flask", "jinja2", "requests"], ["ann", "bob"], 1, "A web framework with templates."),
        ("lab/web2", ["flask", "jinja2", "sqlalchemy"], ["ann", "cat"], 2, "Another web framework for apps."),
        ("lab/cli1", ["click", "rich"], ["dan", "bob"], 1, "A command line toolkit."),
        ("lab/cli2", ["click", "rich", "requests"], ["dan", "eve"], 3, "Command line helper utilities."),
        ("lab/data1", ["numpy", "pandas"], ["fay", "ann"], 4, "Numerical arrays and data frames."),
        ("lab/data2", ["numpy", "scipy", "pandas"], ["fay", "gus"], 2, "Scientific computing with arrays."),
    ]
    base = tmp_path_factory.mktemp("tiny")
    out = []
    for name, pk, authors, br, readme in specs:
        src = make_tiny_repo(base / name.replace("/", "_"), pk, authors, br, readme)
        out.append(build_dna(name, src, tmp_path_factory.mktemp("c")))
    return out
