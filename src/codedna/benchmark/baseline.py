"""The single-database baseline for the benchmark: everything in MongoDB only.

It holds exactly the same data as the hybrid store and answers the same queries, using
the best plain-MongoDB approach for each (indexes, multikey arrays, application-side
joins). If the hybrid design is worthwhile it has to be measured against this.
"""
import time

from codedna.analysis.similarity import Corpus

COLLECTIONS = ("b_repos", "b_commits", "b_docs", "b_calls")


class SingleStoreBaseline:
    def __init__(self, db):
        """`db` is a pymongo Database (a separate one from the hybrid store's MongoDB)."""
        self.db = db
        db.b_repos.create_index("packages")
        db.b_repos.create_index("metrics.avg_cyclomatic")
        db.b_repos.create_index("contributors.name")
        db.b_commits.create_index([("repo_id", 1), ("month", 1)])
        db.b_docs.create_index("repo_id")
        db.b_calls.create_index("repo_id")
        self._corpus = None

    def ingest(self, dna: dict) -> float:
        """Store a Code DNA record. Returns seconds taken."""
        t = time.perf_counter()
        rid = dna["repo_id"]
        self.db.b_repos.replace_one({"_id": rid}, {
            "_id": rid, "metadata": dna["metadata"], "readme": dna["readme"], "config": dna["config"],
            "structure": dna["structure"], "language_share": dna["language_share"],
            "metrics": dna["metrics"], "statistics": dna["evolution_summary"],
            "evolution": dna["evolution_series"], "packages": dna["packages"],
            "contributors": [{"name": n, "commits": c} for n, c in dna["author_counts"].items()],
            "fingerprint": {"packages": dna["packages"], "raw_vectors": dna["raw_vectors"]}}, upsert=True)
        for coll in ("b_commits", "b_docs", "b_calls"):
            self.db[coll].delete_many({"repo_id": rid})
        if dna["commits"]:
            self.db.b_commits.insert_many([{"repo_id": rid, "month": c["time"].strftime("%Y-%m"),
                                            "time": c["time"].replace(tzinfo=None), "sha": c["sha"],
                                            "author": c["author"], "insertions": c["insertions"],
                                            "deletions": c["deletions"]} for c in dna["commits"]])
        if dna["code_docs"]:
            self.db.b_docs.insert_many([dict(d, repo_id=rid) for d in dna["code_docs"]])
        if dna["call_edges"]:
            self.db.b_calls.insert_many([{"repo_id": rid, "caller": a, "callee": b}
                                         for a, b in dna["call_edges"]])
        self._corpus = None
        return time.perf_counter() - t

    def clear(self):
        for coll in COLLECTIONS:
            self.db[coll].delete_many({})
        self._corpus = None

    def repo_ids(self) -> list:
        return sorted(d["_id"] for d in self.db.b_repos.find({}, {"_id": 1}))

    # ---- the same queries as codedna.query.QueryEngine
    def using_technology(self, technology: str) -> list:
        return sorted(d["_id"] for d in self.db.b_repos.find({"packages": technology.lower()}, {"_id": 1}))

    def high_complexity(self, threshold: float = 5.0, top: int = 10) -> list:
        rows = self.db.b_repos.find({"metrics.avg_cyclomatic": {"$gte": threshold}},
                                    {"metrics.avg_cyclomatic": 1})
        out = sorted(((d["_id"], d["metrics"]["avg_cyclomatic"]) for d in rows), key=lambda x: (-x[1], x[0]))
        return [{"repo": r, "avg_cyclomatic": v} for r, v in out[:top]]

    def similar_dependencies(self, repo_id: str, k: int = 5) -> list:
        mine = set((self.db.b_repos.find_one({"_id": repo_id}, {"packages": 1}) or {}).get("packages", []))
        scored = []
        for d in self.db.b_repos.find({"packages": {"$in": list(mine)}, "_id": {"$ne": repo_id}},
                                      {"packages": 1}):
            other = set(d["packages"])
            shared = len(mine & other)
            scored.append((d["_id"], round(shared / (len(mine) + len(other) - shared), 4), sorted(mine & other)))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return [{"repo": r, "score": s, "shared_packages": sh} for r, s, sh in scored[:k]]

    def contributors_of(self, repo_id: str, limit: int = 10) -> dict:
        doc = self.db.b_repos.find_one({"_id": repo_id}, {"contributors": 1}) or {"contributors": []}
        people = sorted(doc["contributors"], key=lambda c: (-c["commits"], c["name"]))
        names = {c["name"] for c in doc["contributors"]}
        connected = []
        for d in self.db.b_repos.find({"contributors.name": {"$in": list(names)}, "_id": {"$ne": repo_id}},
                                      {"contributors.name": 1}):
            n = len(names & {c["name"] for c in d["contributors"]})
            connected.append((d["_id"], n))
        connected.sort(key=lambda x: (-x[1], x[0]))
        return {"contributors": [{"developer": c["name"], "commits": c["commits"]} for c in people[:limit]],
                "connected_repositories": [{"repo": r, "shared_developers": n} for r, n in connected]}

    def similar_to(self, repo_id: str, k: int = 5) -> list:
        if self._corpus is None:
            docs = [{"repo_id": d["_id"], **d["fingerprint"]} for d in self.db.b_repos.find({}, {"fingerprint": 1})]
            self._corpus = Corpus(sorted(docs, key=lambda d: d["repo_id"]))
        return self._corpus.top_k(repo_id, k)
