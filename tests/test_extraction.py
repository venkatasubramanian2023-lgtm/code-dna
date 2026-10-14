from datetime import datetime, timezone

from codedna.extraction import evolution_features, extract_code_features, parse_dependencies
from codedna.extraction.dependencies import third_party_imports
from codedna.preprocessing import count_lines
from codedna.extraction.parser import inheritance_depths, parse_python
from conftest import SAMPLE_APP


def test_count_lines_separates_code_and_comments():
    assert count_lines("x = 1\n# note\n\n// c\ny = 2\n") == (2, 2)


def test_parse_python_finds_structure():
    p = parse_python(SAMPLE_APP)
    assert {c["name"] for c in p["classes"]} == {"Base", "Child"}
    assert {"run", "helper", "main"} <= set(p["functions"])
    # relative import (from . import sibling) is not a third-party module
    assert p["imports"] == ["flask", "numpy", "os", "requests"]
    assert ("run", "helper") in p["calls"]
    assert max(p["complexities"]) >= 4      # Child.run has an if, a for and a nested if


def test_parse_python_returns_none_on_syntax_error():
    assert parse_python("def broken(:\n") is None


def test_inheritance_depth_only_counts_classes_in_repo():
    classes = [{"name": "A", "bases": []}, {"name": "B", "bases": ["A"]},
               {"name": "C", "bases": ["B", "Exception"]}]
    assert sorted(inheritance_depths(classes)) == [0, 1, 2]


def test_inheritance_depth_survives_cycles():
    classes = [{"name": "A", "bases": ["B"]}, {"name": "B", "bases": ["A"]}]
    assert len(inheritance_depths(classes)) == 2


def test_parse_dependencies_requirements_and_package_json():
    deps = parse_dependencies({
        "requirements.txt": "requests>=2.0  # http\nNumPy\n-e .\n# comment\nflask==3.0\n",
        "package.json": '{"dependencies": {"express": "^4"}, "devDependencies": {"Mocha": "1"}}',
    })
    assert deps == {"requests", "numpy", "flask", "express", "mocha"}


def test_parse_dependencies_pyproject():
    toml = '[project]\ndependencies = ["click>=8", "typing_extensions"]\n' \
           '[project.optional-dependencies]\ndev = ["pytest"]\n'
    assert parse_dependencies({"pyproject.toml": toml}) == {"click", "typing-extensions", "pytest"}


def test_parse_dependencies_ignores_bad_json():
    assert parse_dependencies({"package.json": "{not json"}) == set()


def test_third_party_imports_drops_stdlib_and_local():
    imports = {"pkg/app.py": ["os", "requests", "pkg", "util"], "pkg/util.py": ["requests"]}
    counts = third_party_imports(imports, ["pkg/app.py", "pkg/util.py"])
    assert counts == {"requests": 2}


def test_extract_code_features_on_sample_repo(sample_repo):
    f = extract_code_features(sample_repo)
    m = f["metrics"]
    assert m["classes"] == 2
    assert m["functions"] >= 5
    assert m["total_loc"] > 20
    assert 0 < m["comment_ratio"] < 0.5
    assert m["avg_inheritance_depth"] == 0.5          # Base=0, Child=1
    share = f["language_share"]
    assert abs(sum(share.values()) - 1.0) < 0.01
    assert share["Python"] > 0.8 and share["JavaScript"] > 0
    assert set(f["third_party_imports"]) == {"requests", "numpy", "flask"}
    assert ("main", "helper") in f["call_edges"]
    s = f["structure"]
    assert s["has_tests"] and s["has_docs"] and s["has_ci"] and s["has_license"] and s["has_setup"] is False


def test_evolution_features():
    def c(day, author, ins, dele):
        return {"time": datetime(2024, 1, day, tzinfo=timezone.utc), "author": author,
                "insertions": ins, "deletions": dele, "files_changed": 2}
    commits = [c(20, "bob", 5, 1), c(15, "alice", 10, 0), c(10, "alice", 3, 3)]  # newest first
    e = evolution_features(commits)
    assert e["series"] == [{"month": "2024-01", "commits": 3, "churn": 22, "active_authors": 2}]
    s = e["summary"]
    assert s["commits"] == 3 and s["authors"] == 2 and s["span_days"] == 10
    assert s["top_author_share"] == round(2 / 3, 4)
    assert s["total_churn"] == 22


def test_evolution_features_empty():
    e = evolution_features([])
    assert e["summary"]["commits"] == 0 and e["series"] == []
