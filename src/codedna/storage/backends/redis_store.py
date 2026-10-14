"""Key-value store (Redis): repository ID index, compact lookup summaries, query cache."""
import json

from codedna import config


class RedisStore:
    name = "redis"

    def __init__(self):
        import redis
        self.r = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, decode_responses=True)
        self.r.ping()
        self.hits = 0
        self.misses = 0

    # ---- lookup features (stored at ingest, no expiry)
    def put_lookup(self, repo_id: str, summary: dict):
        self.r.set(f"lookup:{repo_id}", json.dumps(summary))
        self.r.sadd("repo_ids", repo_id)

    def get_lookup(self, repo_id: str):
        v = self.r.get(f"lookup:{repo_id}")
        return json.loads(v) if v else None

    def repo_ids(self) -> list:
        return sorted(self.r.smembers("repo_ids"))

    # ---- cache (expires)
    def get(self, key: str):
        v = self.r.get(f"cache:{key}")
        if v is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(v)

    def set(self, key: str, value, ttl: int = None):
        self.r.set(f"cache:{key}", json.dumps(value), ex=ttl or config.REDIS_TTL_SECONDS)

    def clear_cache(self):
        for key in self.r.scan_iter("cache:*"):
            self.r.delete(key)
        self.hits = self.misses = 0

    def clear(self):
        self.r.flushdb()
        self.hits = self.misses = 0
