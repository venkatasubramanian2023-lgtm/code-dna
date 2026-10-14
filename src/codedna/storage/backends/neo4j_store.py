"""Graph store (Neo4j): dependency graph, import graph, call graph, contributor graph.

Nodes:   Repo, Package, File, Function, Developer
Edges:   (Repo)-[:DEPENDS_ON {files}]->(Package)
         (File)-[:IMPORTS]->(Package)      (File)-[:PART_OF]->(Repo)
         (Function)-[:CALLS]->(Function)
         (Developer)-[:COMMITTED_TO {commits}]->(Repo)
"""
from codedna import config

BATCH = 1000
MAX_IMPORT_EDGES = 20000


class Neo4jStore:
    name = "neo4j"

    def __init__(self):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASS))
        self.driver.verify_connectivity()
        with self.driver.session() as s:
            s.run("CREATE CONSTRAINT repo_id IF NOT EXISTS FOR (r:Repo) REQUIRE r.id IS UNIQUE")
            s.run("CREATE CONSTRAINT pkg_name IF NOT EXISTS FOR (p:Package) REQUIRE p.name IS UNIQUE")
            s.run("CREATE CONSTRAINT dev_name IF NOT EXISTS FOR (d:Developer) REQUIRE d.name IS UNIQUE")
            s.run("CREATE INDEX fn_key IF NOT EXISTS FOR (f:Function) ON (f.key)")
            s.run("CREATE INDEX file_key IF NOT EXISTS FOR (f:File) ON (f.key)")

    def save(self, repo_id: str, payload: dict):
        deps = payload["dependency_graph"]
        with self.driver.session() as s:
            # remove the old version of this repository, then write the new one
            s.run("MATCH (n) WHERE (n:Function OR n:File) AND n.repo = $id DETACH DELETE n", id=repo_id)
            s.run("MATCH (r:Repo {id:$id}) DETACH DELETE r", id=repo_id)
            s.run("CREATE (:Repo {id:$id})", id=repo_id)
            s.run("""MATCH (r:Repo {id:$id}) UNWIND $rows AS row
                     MERGE (p:Package {name: row.name})
                     MERGE (r)-[e:DEPENDS_ON]->(p) SET e.files = row.n""",
                  id=repo_id, rows=[{"name": k, "n": v} for k, v in deps["packages"].items()])
            s.run("""MATCH (r:Repo {id:$id}) UNWIND $rows AS row
                     MERGE (d:Developer {name: row.name})
                     MERGE (d)-[e:COMMITTED_TO]->(r) SET e.commits = row.n""",
                  id=repo_id, rows=[{"name": k, "n": v} for k, v in payload["contributor_graph"].items()])
            imports = [{"f": f"{repo_id}:{path}", "path": path, "m": m}
                       for path, mods in deps["imports"].items() for m in mods
                       if m.lower() in deps["packages"]][:MAX_IMPORT_EDGES]
            for i in range(0, len(imports), BATCH):
                s.run("""MATCH (r:Repo {id:$id}) UNWIND $rows AS row
                         MERGE (f:File {key: row.f}) SET f.repo = $id, f.path = row.path
                         MERGE (f)-[:PART_OF]->(r)
                         WITH f, row MATCH (p:Package {name: toLower(row.m)})
                         MERGE (f)-[:IMPORTS]->(p)""", id=repo_id, rows=imports[i:i + BATCH])
            calls = payload["call_graph"]
            for i in range(0, len(calls), BATCH):
                s.run("""UNWIND $rows AS row
                         MERGE (a:Function {key: row.a}) SET a.repo = $id, a.name = row.an
                         MERGE (b:Function {key: row.b}) SET b.repo = $id, b.name = row.bn
                         MERGE (a)-[:CALLS]->(b)""", id=repo_id,
                      rows=[{"a": f"{repo_id}:{a}", "an": a, "b": f"{repo_id}:{b}", "bn": b}
                            for a, b in calls[i:i + BATCH]])

    def _list(self, query: str, key: str, **params) -> list:
        with self.driver.session() as s:
            return [r[key] for r in s.run(query, **params)]

    def packages_of(self, repo_id: str) -> list:
        return self._list("MATCH (:Repo {id:$id})-[:DEPENDS_ON]->(p:Package) RETURN p.name AS x ORDER BY x",
                          "x", id=repo_id)

    def shared_packages(self, a: str, b: str) -> list:
        return self._list("""MATCH (:Repo {id:$a})-[:DEPENDS_ON]->(p:Package)<-[:DEPENDS_ON]-(:Repo {id:$b})
                             RETURN p.name AS x ORDER BY x""", "x", a=a, b=b)

    def repos_using(self, package: str) -> list:
        return self._list("MATCH (r:Repo)-[:DEPENDS_ON]->(:Package {name:$p}) RETURN r.id AS x ORDER BY x",
                          "x", p=package.lower())

    def similar_by_dependencies(self, repo_id: str, k: int = 5) -> list:
        """Other repositories ranked by Jaccard overlap of their package sets."""
        with self.driver.session() as s:
            rows = s.run("""MATCH (a:Repo {id:$id})-[:DEPENDS_ON]->(p:Package)<-[:DEPENDS_ON]-(b:Repo)
                            WHERE a <> b
                            WITH a, b, count(p) AS shared
                            MATCH (a)-[:DEPENDS_ON]->(pa:Package) WITH a, b, shared, count(pa) AS na
                            MATCH (b)-[:DEPENDS_ON]->(pb:Package) WITH b, shared, na, count(pb) AS nb
                            RETURN b.id AS repo, toFloat(shared) / (na + nb - shared) AS score
                            ORDER BY score DESC, repo LIMIT $k""", id=repo_id, k=k)
            return [{"repo": r["repo"], "score": round(r["score"], 4)} for r in rows]

    def contributors_of(self, repo_id: str, limit: int = 20) -> list:
        with self.driver.session() as s:
            return [(r["d"], r["n"]) for r in s.run(
                """MATCH (d:Developer)-[e:COMMITTED_TO]->(:Repo {id:$id})
                   RETURN d.name AS d, e.commits AS n ORDER BY n DESC, d LIMIT $k""", id=repo_id, k=limit)]

    def shared_developers(self, a: str, b: str) -> list:
        return self._list("""MATCH (:Repo {id:$a})<-[:COMMITTED_TO]-(d:Developer)-[:COMMITTED_TO]->(:Repo {id:$b})
                             RETURN d.name AS x ORDER BY x""", "x", a=a, b=b)

    def repos_connected_by_developers(self, repo_id: str) -> list:
        """(other repository, number of shared developers), most connected first."""
        with self.driver.session() as s:
            return [(r["repo"], r["n"]) for r in s.run(
                """MATCH (:Repo {id:$id})<-[:COMMITTED_TO]-(d:Developer)-[:COMMITTED_TO]->(o:Repo)
                   WHERE o.id <> $id RETURN o.id AS repo, count(d) AS n ORDER BY n DESC, repo""", id=repo_id)]

    def most_called(self, repo_id: str, k: int = 10) -> list:
        with self.driver.session() as s:
            return [(r["f"], r["n"]) for r in s.run(
                """MATCH (:Function)-[:CALLS]->(f:Function {repo:$id})
                   RETURN f.name AS f, count(*) AS n ORDER BY n DESC, f LIMIT $k""", id=repo_id, k=k)]

    def clear(self):
        with self.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
