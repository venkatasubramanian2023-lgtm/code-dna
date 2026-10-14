"""Wide-column store (Cassandra): software metrics, repository statistics, commit history,
monthly evolution time series.

repo_metrics     one wide row per repository (many numeric columns)
repo_statistics  one wide row per repository (history summary)
commits          partition (repo_id, month), clustered by commit time, newest first
evolution        partition repo_id, clustered by month
"""
from codedna import config

METRIC_COLUMNS = {"files": "int", "total_loc": "int", "comment_ratio": "double", "functions": "int",
                  "classes": "int", "avg_cyclomatic": "double", "max_cyclomatic": "int",
                  "avg_inheritance_depth": "double"}
STAT_COLUMNS = {"commits": "int", "authors": "int", "span_days": "int", "commits_per_month": "double",
                "total_churn": "bigint", "top_author_share": "double", "avg_files_per_commit": "double",
                "total_commits": "int"}


def _create_table(name: str, columns: dict) -> str:
    cols = ", ".join(f"{c} {t}" for c, t in columns.items())
    return f"CREATE TABLE IF NOT EXISTS {name} (repo_id text PRIMARY KEY, {cols})"


class CassandraStore:
    name = "cassandra"

    def __init__(self):
        from cassandra.cluster import Cluster
        self.cluster = Cluster(config.CASSANDRA_HOSTS, connect_timeout=5)
        self.session = self.cluster.connect()
        self.session.execute(f"""CREATE KEYSPACE IF NOT EXISTS {config.CASSANDRA_KEYSPACE}
            WITH replication = {{'class':'SimpleStrategy','replication_factor':1}}""")
        self.session.set_keyspace(config.CASSANDRA_KEYSPACE)
        self.session.execute(_create_table("repo_metrics", METRIC_COLUMNS))
        self.session.execute(_create_table("repo_statistics", STAT_COLUMNS))
        self.session.execute("""CREATE TABLE IF NOT EXISTS commits (
            repo_id text, month text, commit_time timestamp, sha text, author text,
            files_changed int, insertions int, deletions int,
            PRIMARY KEY ((repo_id, month), commit_time, sha))
            WITH CLUSTERING ORDER BY (commit_time DESC, sha ASC)""")
        self.session.execute("""CREATE TABLE IF NOT EXISTS evolution (
            repo_id text, month text, commits int, churn int, active_authors int,
            PRIMARY KEY (repo_id, month))""")
        self._ins_commit = self.session.prepare(
            "INSERT INTO commits (repo_id, month, commit_time, sha, author, files_changed, insertions, "
            "deletions) VALUES (?,?,?,?,?,?,?,?)")
        self._ins_evo = self.session.prepare(
            "INSERT INTO evolution (repo_id, month, commits, churn, active_authors) VALUES (?,?,?,?,?)")

    def _save_row(self, table: str, columns: dict, repo_id: str, values: dict):
        names = ["repo_id"] + list(columns)
        marks = ",".join("?" * len(names))
        stmt = self.session.prepare(f"INSERT INTO {table} ({','.join(names)}) VALUES ({marks})")
        self.session.execute(stmt, [repo_id] + [values.get(c) for c in columns])

    def save(self, repo_id: str, payload: dict):
        from cassandra.concurrent import execute_concurrent_with_args
        self._save_row("repo_metrics", METRIC_COLUMNS, repo_id, payload["metrics"])
        self._save_row("repo_statistics", STAT_COLUMNS, repo_id, payload["repo_statistics"])
        # re-ingesting replaces the old history of this repository
        for row in self.session.execute("SELECT month FROM evolution WHERE repo_id=%s", (repo_id,)):
            self.session.execute("DELETE FROM commits WHERE repo_id=%s AND month=%s", (repo_id, row.month))
        self.session.execute("DELETE FROM evolution WHERE repo_id=%s", (repo_id,))
        execute_concurrent_with_args(self.session, self._ins_commit, [
            (repo_id, c["time"].strftime("%Y-%m"), c["time"].replace(tzinfo=None), c["sha"], c["author"],
             c["files_changed"], c["insertions"], c["deletions"]) for c in payload["commit_history"]])
        execute_concurrent_with_args(self.session, self._ins_evo, [
            (repo_id, s["month"], s["commits"], s["churn"], s["active_authors"])
            for s in payload["evolution_series"]])

    def metrics(self, repo_id: str) -> dict:
        row = self.session.execute("SELECT * FROM repo_metrics WHERE repo_id=%s", (repo_id,)).one()
        return {c: getattr(row, c) for c in METRIC_COLUMNS} if row else {}

    def statistics(self, repo_id: str) -> dict:
        row = self.session.execute("SELECT * FROM repo_statistics WHERE repo_id=%s", (repo_id,)).one()
        return {c: getattr(row, c) for c in STAT_COLUMNS} if row else {}

    def all_metrics(self) -> dict:
        """repo_id -> metrics for every repository (a small table, so a full scan is fine)."""
        return {r.repo_id: {c: getattr(r, c) for c in METRIC_COLUMNS}
                for r in self.session.execute("SELECT * FROM repo_metrics")}

    def evolution(self, repo_id: str) -> list:
        rows = self.session.execute(
            "SELECT month, commits, churn, active_authors FROM evolution WHERE repo_id=%s", (repo_id,))
        return [dict(month=r.month, commits=r.commits, churn=r.churn, active_authors=r.active_authors)
                for r in rows]

    def commits_in_month(self, repo_id: str, month: str) -> list:
        rows = self.session.execute(
            "SELECT commit_time, sha, author, insertions, deletions FROM commits "
            "WHERE repo_id=%s AND month=%s", (repo_id, month))
        return [dict(time=r.commit_time, sha=r.sha, author=r.author, insertions=r.insertions,
                     deletions=r.deletions) for r in rows]

    def clear(self):
        for table in ("repo_metrics", "repo_statistics", "commits", "evolution"):
            self.session.execute(f"TRUNCATE {table}")
