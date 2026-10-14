"""In-memory stand-ins with the same methods as the four real backends.

Used for unit tests and when CODEDNA_FALLBACK=1 and a database is unreachable, so the
logic can run without Docker. Results reported in the paper must come from the real
databases. tests/test_storage_contract.py runs the same checks against both.
"""
import json
from collections import defaultdict

from codedna.storage.backends.cassandra_store import METRIC_COLUMNS, STAT_COLUMNS


class MemoryMongo:
    name = "mongodb"

    def __init__(self):
        self.repos, self.docs, self.fps = {}, {}, {}

    def save(self, repo_id, payload, fingerprint):
        self.repos[repo_id] = {k: payload[k] for k in
                               ("metadata", "readme", "config", "structure", "language_share")}
        self.docs[repo_id] = list(payload["code_docs"])
        self.fps[repo_id] = dict(fingerprint, repo_id=repo_id)

    def get_repo(self, repo_id):
        return dict(self.repos.get(repo_id, {}))

    def list_ids(self):
        return sorted(self.repos)

    def fingerprints(self):
        return list(self.fps.values())

    def code_docs(self, repo_id):
        return list(self.docs.get(repo_id, []))

    def search_readme(self, text, limit=10):
        t = text.lower()
        return sorted(k for k, v in self.repos.items() if t in (v["readme"] or "").lower())[:limit]

    def find_by_metadata(self, **conditions):
        return sorted(k for k, v in self.repos.items()
                      if all(v["metadata"].get(f) == x for f, x in conditions.items()))

    def clear(self):
        self.__init__()


class MemoryNeo4j:
    name = "neo4j"

    def __init__(self):
        self.deps, self.devs, self.calls = {}, {}, {}

    def save(self, repo_id, payload):
        self.deps[repo_id] = dict(payload["dependency_graph"]["packages"])
        self.devs[repo_id] = dict(payload["contributor_graph"])
        self.calls[repo_id] = [tuple(e) for e in payload["call_graph"]]

    def packages_of(self, repo_id):
        return sorted(self.deps.get(repo_id, {}))

    def shared_packages(self, a, b):
        return sorted(set(self.deps.get(a, {})) & set(self.deps.get(b, {})))

    def repos_using(self, package):
        return sorted(r for r, d in self.deps.items() if package.lower() in d)

    def similar_by_dependencies(self, repo_id, k=5):
        mine = set(self.deps.get(repo_id, {}))
        scored = []
        for other, d in self.deps.items():
            if other == repo_id:
                continue
            shared = len(mine & set(d))
            if shared:
                scored.append((other, round(shared / (len(mine) + len(d) - shared), 4)))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return [{"repo": r, "score": s} for r, s in scored[:k]]

    def contributors_of(self, repo_id, limit=20):
        return sorted(self.devs.get(repo_id, {}).items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    def shared_developers(self, a, b):
        return sorted(set(self.devs.get(a, {})) & set(self.devs.get(b, {})))

    def repos_connected_by_developers(self, repo_id):
        mine = set(self.devs.get(repo_id, {}))
        out = [(o, len(mine & set(d))) for o, d in self.devs.items() if o != repo_id and mine & set(d)]
        return sorted(out, key=lambda x: (-x[1], x[0]))

    def most_called(self, repo_id, k=10):
        n = defaultdict(int)
        for _, b in self.calls.get(repo_id, []):
            n[b] += 1
        return sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))[:k]

    def clear(self):
        self.__init__()


class MemoryCassandra:
    name = "cassandra"

    def __init__(self):
        self.metric_rows, self.stat_rows, self.commit_rows, self.evo = {}, {}, defaultdict(list), {}

    def save(self, repo_id, payload):
        self.metric_rows[repo_id] = {c: payload["metrics"].get(c) for c in METRIC_COLUMNS}
        self.stat_rows[repo_id] = {c: payload["repo_statistics"].get(c) for c in STAT_COLUMNS}
        for key in [k for k in self.commit_rows if k[0] == repo_id]:
            del self.commit_rows[key]
        for c in payload["commit_history"]:
            self.commit_rows[(repo_id, c["time"].strftime("%Y-%m"))].append(
                dict(time=c["time"].replace(tzinfo=None), sha=c["sha"], author=c["author"],
                     insertions=c["insertions"], deletions=c["deletions"]))
        self.evo[repo_id] = [dict(s) for s in payload["evolution_series"]]

    def metrics(self, repo_id):
        return dict(self.metric_rows.get(repo_id, {}))

    def statistics(self, repo_id):
        return dict(self.stat_rows.get(repo_id, {}))

    def all_metrics(self):
        return {r: dict(m) for r, m in self.metric_rows.items()}

    def evolution(self, repo_id):
        return sorted((dict(s) for s in self.evo.get(repo_id, [])), key=lambda s: s["month"])

    def commits_in_month(self, repo_id, month):
        return sorted(self.commit_rows.get((repo_id, month), []), key=lambda c: c["time"], reverse=True)

    def clear(self):
        self.__init__()


class MemoryRedis:
    name = "redis"

    def __init__(self):
        self.lookups, self.cache, self.hits, self.misses = {}, {}, 0, 0

    def put_lookup(self, repo_id, summary):
        self.lookups[repo_id] = json.dumps(summary)

    def get_lookup(self, repo_id):
        v = self.lookups.get(repo_id)
        return json.loads(v) if v else None

    def repo_ids(self):
        return sorted(self.lookups)

    def get(self, key):
        if key in self.cache:
            self.hits += 1
            return json.loads(self.cache[key])
        self.misses += 1
        return None

    def set(self, key, value, ttl=None):
        self.cache[key] = json.dumps(value)

    def clear_cache(self):
        self.cache, self.hits, self.misses = {}, 0, 0

    def clear(self):
        self.__init__()
