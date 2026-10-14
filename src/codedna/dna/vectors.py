"""Raw sub-vectors that make up a Code DNA fingerprint (layout in docs/SCHEMA.md).

These are the per-repository raw values. Corpus-level scaling (z-scores and L2
normalisation) happens in analysis/similarity.py because it needs all repositories.
"""
import hashlib
import math
from collections import Counter

from codedna import config
from codedna.preprocessing import LANG_ORDER


def metrics_vector(m: dict) -> list:
    """8 values: log-scaled size counts, complexity, inheritance depth and comment ratio."""
    return [math.log1p(m["files"]), math.log1p(m["total_loc"]), math.log1p(m["functions"]),
            math.log1p(m["classes"]), m["avg_cyclomatic"], math.log1p(m["max_cyclomatic"]),
            m["avg_inheritance_depth"], m["comment_ratio"]]


def language_vector(share: dict) -> list:
    """12 values: share of code per language, in the fixed LANG_ORDER."""
    return [share.get(lang, 0.0) for lang in LANG_ORDER]


def _hash_slot(token: str, dim: int):
    h = int(hashlib.md5(token.encode()).hexdigest(), 16)
    return h % dim, (1.0 if (h >> 64) % 2 == 0 else -1.0)   # signed hashing trick


def dependency_vector(packages) -> list:
    """64 values: hashed bag of package names. Identical package sets give identical vectors."""
    vec = [0.0] * config.DIM_DEPENDENCY
    for pkg in packages:
        slot, sign = _hash_slot(pkg, config.DIM_DEPENDENCY)
        vec[slot] += sign
    return vec


def structure_vector(s: dict, readme_len: int) -> list:
    """16 values: 8-bin folder-depth histogram, 6 yes/no flags, entry count, README length."""
    flags = [float(s[k]) for k in ("has_tests", "has_docs", "has_ci", "has_setup",
                                    "has_license", "has_docker")]
    return list(s["depth_hist"]) + flags + [math.log1p(s["top_level_entries"]) / 4.0,
                                            math.log1p(readme_len) / 10.0]


def bus_factor(author_counts: dict) -> int:
    """Smallest number of authors who made at least half of all commits."""
    total, running, n = sum(author_counts.values()), 0, 0
    for _, count in sorted(author_counts.items(), key=lambda kv: -kv[1]):
        running += count
        n += 1
        if running >= total / 2:
            break
    return n


def evolution_vector(e: dict) -> list:
    """8 values: commit volume and rate, authors, age, churn, concentration, bus factor."""
    s = e["summary"]
    return [math.log1p(s["commits"]), math.log1p(s["authors"]), math.log1p(s["span_days"]),
            math.log1p(s["commits_per_month"]), math.log1p(s["total_churn"]),
            s["top_author_share"], math.log1p(bus_factor(e["author_counts"])),
            math.log1p(s["avg_files_per_commit"])]


def semantic_vector(tokens) -> list:
    """64 values: hashed bag of words with sublinear term frequency (1 + log tf).

    A dependency-free stand-in for neural embeddings; the rest of the pipeline only
    needs a fixed-length vector, so sentence-transformers can replace this later.
    """
    vec = [0.0] * config.DIM_SEMANTIC
    for word, count in Counter(tokens).items():
        slot, sign = _hash_slot(word, config.DIM_SEMANTIC)
        vec[slot] += sign * (1.0 + math.log(count))
    return vec
