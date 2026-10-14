"""Step 1: repository collection.

Clones repositories with git and reads everything available from the clone
(commit history, README, dependency manifests). If GITHUB_TOKEN is set, the
GitHub API adds stars, forks, topics, license and description.
"""
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from codedna import config

MANIFESTS = ("requirements.txt", "setup.py", "setup.cfg", "pyproject.toml", "Pipfile",
             "package.json", "pom.xml", "build.gradle", "go.mod")


def clone(full_name: str, dest_root: str = None, source: str = None) -> str:
    """Clone owner/name into dest_root and return the local path.

    `source` overrides the remote (a local path or URL); the tests use it.
    """
    dest_root = dest_root or config.REPO_DIR
    os.makedirs(dest_root, exist_ok=True)
    dest = os.path.join(dest_root, full_name.replace("/", "__"))
    if os.path.isdir(os.path.join(dest, ".git")):
        return dest
    url = source or f"https://github.com/{full_name}.git"
    subprocess.run(["git", "clone", "--quiet", url, dest], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dest


def _git(path: str, *args: str) -> str:
    out = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout


SEP = "\x1f"
PARALLEL_MIN_COMMITS = 400      # below this, one git process is just as fast
MIN_CHUNK = 100                 # smallest slice of history given to one git process


def _log_chunk(path: str, skip: int, count: int) -> str:
    return _git(path, "log", f"--skip={skip}", f"-n{count}",
                f"--pretty=format:@@C{SEP}%H{SEP}%at{SEP}%an{SEP}%ae", "--numstat")


def _parse_log(raw: str) -> list:
    commits, cur = [], None
    for line in raw.splitlines():
        if line.startswith("@@C"):
            _, sha, ts, name, email = line.split(SEP)
            cur = {"sha": sha, "time": datetime.fromtimestamp(int(ts), timezone.utc),
                   "author": name, "email": email,
                   "files_changed": 0, "insertions": 0, "deletions": 0}
            commits.append(cur)
        elif line.strip() and cur is not None:
            parts = line.split("\t")
            if len(parts) == 3:
                cur["files_changed"] += 1
                cur["insertions"] += int(parts[0]) if parts[0].isdigit() else 0
                cur["deletions"] += int(parts[1]) if parts[1].isdigit() else 0
    return commits


def read_commits(path: str, limit: int = None, jobs: int = None) -> list:
    """One dict per commit, newest first: time, author, and lines added / removed.

    For long histories the log is read in several chunks at once (git spends its time
    computing diffs, so this scales with the number of cores). The result is the same
    as one single `git log`.
    """
    limit = limit or config.MAX_COMMITS
    jobs = jobs or config.WORKERS
    n = min(limit, total_commits(path))
    if jobs > 1 and n >= PARALLEL_MIN_COMMITS:
        size = max(MIN_CHUNK, -(-n // (jobs * 3)))                 # about three chunks per worker
        chunks = [(start, min(size, n - start)) for start in range(0, n, size)]
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            raw = "\n".join(pool.map(lambda c: _log_chunk(path, *c), chunks))
    else:
        raw = _log_chunk(path, 0, limit)
    return _parse_log(raw)


def read_branches(path: str) -> list:
    """Names of the remote branches of the clone (falls back to local branches)."""
    out = _git(path, "branch", "-r", "--format=%(refname:short)").split()
    names = [b.split("/", 1)[1] for b in out if "/" in b and not b.endswith("/HEAD")]
    if not names:
        names = _git(path, "branch", "--format=%(refname:short)").split()
    return sorted(set(names))


def first_commit_time(path: str):
    """Time of the repository's first commit (earliest root commit), not limited by MAX_COMMITS."""
    stamps = [int(x) for x in _git(path, "log", "--max-parents=0", "--format=%at").split()]
    return datetime.fromtimestamp(min(stamps), timezone.utc) if stamps else None


def total_commits(path: str) -> int:
    """Real number of commits on HEAD (read_commits stops at MAX_COMMITS)."""
    out = _git(path, "rev-list", "--count", "HEAD").strip()
    return int(out) if out.isdigit() else 0


def read_readme(path: str) -> str:
    """README text. Matches any file named readme.* in any letter case (Readme.md, README.rst)."""
    names = sorted(n for n in os.listdir(path)
                   if n.lower().split(".")[0] == "readme" and os.path.isfile(os.path.join(path, n)))
    # prefer markdown, then rst, then anything else
    names.sort(key=lambda n: (not n.lower().endswith(".md"), not n.lower().endswith(".rst"), n))
    if not names:
        return ""
    with open(os.path.join(path, names[0]), encoding="utf-8", errors="replace") as f:
        return f.read()[:20000]


def read_dependency_files(path: str) -> dict:
    """Raw text of the dependency manifests found in the repository root."""
    found = {}
    for name in MANIFESTS:
        p = os.path.join(path, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                found[name] = f.read()[:50000]
    return found


def api_metadata(full_name: str) -> dict:
    """Optional GitHub API enrichment. Returns {} without a token or on any failure."""
    if not config.GITHUB_TOKEN:
        return {}
    try:
        r = requests.get(f"https://api.github.com/repos/{full_name}",
                         headers={"Authorization": f"Bearer {config.GITHUB_TOKEN}"}, timeout=20)
        if r.status_code != 200:
            return {}
        d = r.json()
        meta = {"stars": d.get("stargazers_count"), "forks": d.get("forks_count"),
                "topics": d.get("topics", []), "license": (d.get("license") or {}).get("spdx_id"),
                "description": d.get("description"), "api_language": d.get("language"),
                "created_at": d.get("created_at"), "open_issues": d.get("open_issues_count")}
        meta["pull_requests"] = _count_pull_requests(full_name)
        return meta
    except requests.RequestException:
        return {}


def _count_pull_requests(full_name: str):
    """Total pull requests (open and closed) through the search API; None if unavailable."""
    try:
        r = requests.get("https://api.github.com/search/issues",
                         params={"q": f"repo:{full_name} is:pr", "per_page": 1},
                         headers={"Authorization": f"Bearer {config.GITHUB_TOKEN}"}, timeout=20)
        return r.json().get("total_count") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def collect(full_name: str, source: str = None) -> dict:
    """Collect everything the later stages need for one repository."""
    path = clone(full_name, source=source)
    return {
        "full_name": full_name,
        "path": path,
        "head": _git(path, "rev-parse", "HEAD").strip(),
        "commits": read_commits(path),
        "total_commits": total_commits(path),
        "first_commit": first_commit_time(path),
        "branches": read_branches(path),
        "readme": read_readme(path),
        "dependency_files": read_dependency_files(path),
        "api": api_metadata(full_name),
    }
