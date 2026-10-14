"""Document store (MongoDB): metadata, README, config, per-file summaries, structure,
language share and the fingerprint vectors."""
from codedna import config


class MongoStore:
    name = "mongodb"

    def __init__(self):
        from pymongo import MongoClient
        self.client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
        self.client.admin.command("ping")
        self.db = self.client[config.MONGO_DB]
        self.db.repos.create_index("owner")
        self.db.code_docs.create_index("repo_id")

    def save(self, repo_id: str, payload: dict, fingerprint: dict):
        self.db.repos.replace_one({"_id": repo_id}, {
            "_id": repo_id,
            "metadata": payload["metadata"], "readme": payload["readme"],
            "config": payload["config"], "structure": payload["structure"],
            "language_share": payload["language_share"]}, upsert=True)
        self.db.code_docs.delete_many({"repo_id": repo_id})
        docs = [dict(d, repo_id=repo_id) for d in payload["code_docs"]]
        if docs:
            self.db.code_docs.insert_many(docs)
        self.db.fingerprints.replace_one({"_id": repo_id}, dict(fingerprint, _id=repo_id), upsert=True)

    def get_repo(self, repo_id: str) -> dict:
        doc = self.db.repos.find_one({"_id": repo_id}) or {}
        doc.pop("_id", None)
        return doc

    def list_ids(self) -> list:
        return sorted(d["_id"] for d in self.db.repos.find({}, {"_id": 1}))

    def fingerprints(self) -> list:
        return [dict(d, repo_id=d["_id"]) for d in self.db.fingerprints.find({})]

    def code_docs(self, repo_id: str) -> list:
        return [{k: v for k, v in d.items() if k not in ("_id", "repo_id")}
                for d in self.db.code_docs.find({"repo_id": repo_id})]

    def search_readme(self, text: str, limit: int = 10) -> list:
        import re
        return sorted(d["_id"] for d in self.db.repos.find(
            {"readme": {"$regex": re.escape(text), "$options": "i"}}, {"_id": 1}).limit(limit))

    def find_by_metadata(self, **conditions) -> list:
        """Repository IDs whose metadata fields equal the given values."""
        query = {f"metadata.{k}": v for k, v in conditions.items()}
        return sorted(d["_id"] for d in self.db.repos.find(query, {"_id": 1}))

    def clear(self):
        for c in ("repos", "code_docs", "fingerprints"):
            self.db[c].delete_many({})
