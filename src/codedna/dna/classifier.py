"""Steps 6-7: feature classification and NoSQL model mapping (the data-aware storage rule).

Each feature group has a profile describing the shape of its data. choose_store()
picks the database from that profile, so the mapping is a rule that can be tested
and reported in the paper, not a hand-drawn table.
"""
from dataclasses import dataclass

MONGODB, NEO4J, CASSANDRA, REDIS = "mongodb", "neo4j", "cassandra", "redis"


@dataclass(frozen=True)
class Profile:
    relational: bool = False    # mostly about links between entities
    wide_column: bool = False   # wide numeric records, or large time-ordered data
    hot: bool = False           # read often, short lived, looked up by key


def choose_store(p: Profile) -> str:
    """Rule order matters: relationships, then wide / time-ordered data, then hot data.
    Everything nested or variable in shape falls through to the document store."""
    if p.relational:
        return NEO4J
    if p.wide_column:
        return CASSANDRA
    if p.hot:
        return REDIS
    return MONGODB


FEATURE_PROFILES = {
    # document store: JSON with a flexible schema
    "metadata": Profile(),
    "readme": Profile(),
    "config": Profile(),
    "code_docs": Profile(),
    "structure": Profile(),
    "language_share": Profile(),
    "fingerprint": Profile(),
    # graph store: relationships
    "dependency_graph": Profile(relational=True),
    "call_graph": Profile(relational=True),
    "contributor_graph": Profile(relational=True),
    # wide-column store: metrics, statistics, history, time series
    "metrics": Profile(wide_column=True),
    "repo_statistics": Profile(wide_column=True),
    "commit_history": Profile(wide_column=True),
    "evolution_series": Profile(wide_column=True),
    # key-value store: lookups and cache
    "lookup": Profile(hot=True),
    "similarity_cache": Profile(hot=True),
    "repo_cache": Profile(hot=True),
}

# groups written when a repository is ingested (cache groups are written at query time)
STORED_AT_INGEST = ("metadata", "readme", "config", "code_docs", "structure", "language_share",
                    "dependency_graph", "call_graph", "contributor_graph",
                    "metrics", "repo_statistics", "commit_history", "evolution_series", "lookup")


def mapping() -> dict:
    """feature group -> database name (the mapping table reported in the paper)."""
    return {name: choose_store(p) for name, p in FEATURE_PROFILES.items()}


def lookup_summary(dna: dict) -> dict:
    """Compact per-repository summary kept in Redis for fast lookups."""
    langs = dna["language_share"]
    return {
        "repo_id": dna["repo_id"],
        "main_language": max(langs, key=langs.get) if any(langs.values()) else None,
        "loc": dna["metrics"]["total_loc"],
        "files": dna["metrics"]["files"],
        "avg_cyclomatic": dna["metrics"]["avg_cyclomatic"],
        "commits": dna["metadata"]["total_commits"],
        "contributors": dna["evolution_summary"]["authors"],
        "packages": len(dna["packages"]),
    }


def route(dna: dict) -> dict:
    """Split one DNA record into the payload each database should receive."""
    source = {
        "metadata": dna["metadata"],
        "readme": dna["readme"],
        "config": dna["config"],
        "code_docs": dna["code_docs"],
        "structure": dna["structure"],
        "language_share": dna["language_share"],
        # same package set as the fingerprint; the number is how many files import it (0 = declared only)
        "dependency_graph": {"packages": {p: dna["package_counts"].get(p, 0) for p in dna["packages"]},
                             "imports": dna["imports_by_file"]},
        "call_graph": dna["call_edges"],
        "contributor_graph": dna["author_counts"],
        "metrics": dna["metrics"],
        # evolution_summary covers the newest MAX_COMMITS commits; total_commits is the real count
        "repo_statistics": {**dna["evolution_summary"], "total_commits": dna["metadata"]["total_commits"]},
        "commit_history": dna["commits"],
        "evolution_series": dna["evolution_series"],
        "lookup": lookup_summary(dna),
    }
    m = mapping()
    payload = {MONGODB: {}, NEO4J: {}, CASSANDRA: {}, REDIS: {}}
    for feature in STORED_AT_INGEST:
        payload[m[feature]][feature] = source[feature]
    return payload
