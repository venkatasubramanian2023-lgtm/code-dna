"""Step 9: query processing.

The five queries from the methodology. Each one is answered by the database whose data
model suits it, and every result reports which databases were used and how long it took.
"""
import time

from codedna.storage import HybridStore

COMPLEXITY_METRICS = ("avg_cyclomatic", "max_cyclomatic", "avg_inheritance_depth", "total_loc",
                      "files", "functions", "classes", "comment_ratio")


class UnknownRepository(KeyError):
    pass


class QueryEngine:
    def __init__(self, store: HybridStore):
        self.store = store

    def _require(self, repo_id: str):
        if self.store.lookup(repo_id) is None:
            raise UnknownRepository(repo_id)

    @staticmethod
    def _answer(name, params, results, databases, started):
        return {"query": name, "params": params, "results": results, "databases": databases,
                "ms": round((time.perf_counter() - started) * 1000, 2)}

    # 1. Find repositories similar to X
    def similar_to(self, repo_id: str, k: int = 5) -> dict:
        t = time.perf_counter()
        self._require(repo_id)
        return self._answer("similar_to", {"repo": repo_id, "k": k},
                            self.store.similar(repo_id, k), ["mongodb", "redis"], t)

    # 2. Find repositories using a technology (React, flask, numpy, ...)
    def using_technology(self, technology: str) -> dict:
        t = time.perf_counter()
        repos = self.store.neo4j.repos_using(technology)
        return self._answer("using_technology", {"technology": technology}, repos, ["neo4j"], t)

    # 3. Find projects with high complexity
    def high_complexity(self, threshold: float = 5.0, metric: str = "avg_cyclomatic", top: int = 10) -> dict:
        t = time.perf_counter()
        if metric not in COMPLEXITY_METRICS:
            raise ValueError(f"metric must be one of {COMPLEXITY_METRICS}")
        rows = [(r, m[metric]) for r, m in self.store.cassandra.all_metrics().items()
                if m.get(metric) is not None and m[metric] >= threshold]
        rows.sort(key=lambda x: (-x[1], x[0]))
        results = [{"repo": r, metric: v} for r, v in rows[:top]]
        return self._answer("high_complexity", {"metric": metric, "threshold": threshold, "top": top},
                            results, ["cassandra"], t)

    # 4. Find repositories with similar dependency structures
    def similar_dependencies(self, repo_id: str, k: int = 5) -> dict:
        t = time.perf_counter()
        self._require(repo_id)
        results = self.store.neo4j.similar_by_dependencies(repo_id, k)
        for r in results:
            r["shared_packages"] = self.store.neo4j.shared_packages(repo_id, r["repo"])
        return self._answer("similar_dependencies", {"repo": repo_id, "k": k}, results,
                            ["redis", "neo4j"], t)

    # 5. Find contributors connected to repository X
    def contributors_of(self, repo_id: str, limit: int = 10) -> dict:
        t = time.perf_counter()
        self._require(repo_id)
        results = {"contributors": [{"developer": d, "commits": n}
                                    for d, n in self.store.neo4j.contributors_of(repo_id, limit)],
                   "connected_repositories": [{"repo": r, "shared_developers": n} for r, n in
                                              self.store.neo4j.repos_connected_by_developers(repo_id)]}
        return self._answer("contributors_of", {"repo": repo_id, "limit": limit}, results,
                            ["redis", "neo4j"], t)

    # extra: filter and search
    def by_language(self, language: str) -> dict:
        """Repositories whose main language is `language`, from the Redis lookup summaries."""
        t = time.perf_counter()
        repos = [r for r in self.store.repo_ids()
                 if (self.store.lookup(r) or {}).get("main_language", "").lower() == language.lower()]
        return self._answer("by_language", {"language": language}, repos, ["redis"], t)

    def search_readme(self, text: str, limit: int = 10) -> dict:
        t = time.perf_counter()
        return self._answer("search_readme", {"text": text, "limit": limit},
                            self.store.mongo.search_readme(text, limit), ["mongodb"], t)

    def run(self, name: str, **params) -> dict:
        """Run a query by name; used by the API and the benchmark."""
        if name not in QUERIES:
            raise ValueError(f"unknown query {name!r}; choose from {sorted(QUERIES)}")
        return getattr(self, name)(**params)


QUERIES = ("similar_to", "using_technology", "high_complexity", "similar_dependencies",
           "contributors_of", "by_language", "search_readme")
