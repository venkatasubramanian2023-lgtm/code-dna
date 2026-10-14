from datetime import timezone

from codedna.collection import github


def test_collect_reads_commits_readme_and_manifests(sample_repo, tmp_path, monkeypatch):
    monkeypatch.setattr("codedna.config.REPO_DIR", str(tmp_path / "repos"))
    c = github.collect("acme/sample", source=sample_repo)
    assert c["full_name"] == "acme/sample"
    assert len(c["head"]) == 40
    assert len(c["commits"]) == 3
    newest = c["commits"][0]
    assert newest["author"] == "alice" and newest["time"].tzinfo == timezone.utc
    assert newest["time"].strftime("%Y-%m") == "2024-03"
    assert c["readme"].startswith("# Sample")
    assert list(c["dependency_files"]) == ["requirements.txt"]
    assert c["api"] == {}                      # no GITHUB_TOKEN set


def test_clone_is_reused_when_present(sample_repo, tmp_path):
    first = github.clone("acme/sample", str(tmp_path), source=sample_repo)
    second = github.clone("acme/sample", str(tmp_path), source="/does/not/exist")
    assert first == second


def test_read_commits_counts_line_changes(sample_repo, tmp_path):
    path = github.clone("acme/sample", str(tmp_path), source=sample_repo)
    commits = github.read_commits(path)
    assert commits[-1]["insertions"] > 0 and commits[-1]["files_changed"] >= 5
    assert sum(c["deletions"] for c in commits) >= 1     # the third commit removed a line


def test_branches_first_commit_and_total(sample_repo, tmp_path):
    path = github.clone("acme/sample", str(tmp_path), source=sample_repo)
    assert len(github.read_branches(path)) >= 1
    assert github.first_commit_time(path).strftime("%Y-%m-%d") == "2024-01-10"
    assert github.total_commits(path) == 3


def test_readme_found_in_any_letter_case(tmp_path):
    (tmp_path / "Readme.md").write_text("# Express style name")
    assert github.read_readme(str(tmp_path)).startswith("# Express")
    other = tmp_path / "b"
    other.mkdir()
    (other / "README.rst").write_text("rst text")
    (other / "README.md").write_text("md text")
    assert github.read_readme(str(other)) == "md text"        # markdown preferred
    empty = tmp_path / "c"
    empty.mkdir()
    assert github.read_readme(str(empty)) == ""
