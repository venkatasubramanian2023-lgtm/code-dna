"""Repository structure features: folder depth and the presence of tests, docs, CI and so on."""
import os
from collections import Counter

from codedna.preprocessing import walk_files


def structure_features(root: str) -> dict:
    top = {e.lower() for e in os.listdir(root)}
    depths = Counter()
    for path in walk_files(root):
        depths[min(os.path.relpath(path, root).count(os.sep), 7)] += 1
    total = sum(depths.values()) or 1
    return {
        "has_tests": any(t in top for t in ("tests", "test", "spec")),
        "has_docs": any(t in top for t in ("docs", "doc", "documentation")),
        "has_ci": any(t in top for t in (".github", ".travis.yml", ".gitlab-ci.yml",
                                         "azure-pipelines.yml", ".circleci")),
        "has_setup": any(t in top for t in ("setup.py", "pyproject.toml", "package.json",
                                            "pom.xml", "go.mod")),
        "has_license": any(t.startswith("license") for t in top),
        "has_docker": "dockerfile" in top or "docker-compose.yml" in top,
        "top_level_entries": len(top),
        "depth_hist": [round(depths.get(i, 0) / total, 4) for i in range(8)],
    }
