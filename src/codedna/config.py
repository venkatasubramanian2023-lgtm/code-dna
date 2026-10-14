"""Central settings. Every value can be overridden with an environment variable
(see .env.example). Modules read from here and never hard-code connection details.
"""
import os

# ---- paths (relative to the directory the command is run from)
DATA_DIR = os.environ.get("CODEDNA_DATA", "data")
REPO_DIR = os.path.join(DATA_DIR, "repos")
RESULTS_DIR = os.environ.get("CODEDNA_RESULTS", "results")
DATASETS_DIR = os.environ.get("CODEDNA_DATASETS", "datasets")

# ---- databases
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "codedna")
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("NEO4J_PASS", "codedna_pass")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_TTL_SECONDS = int(os.environ.get("REDIS_TTL_SECONDS", "3600"))
CASSANDRA_HOSTS = os.environ.get("CASSANDRA_HOSTS", "localhost").split(",")
CASSANDRA_KEYSPACE = os.environ.get("CASSANDRA_KEYSPACE", "codedna")

# Use in-memory stand-ins for databases that are not reachable. For tests only:
# results reported in the paper must come from the real databases.
ALLOW_FALLBACK = os.environ.get("CODEDNA_FALLBACK", "0") == "1"

# ---- GitHub
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")  # optional: adds stars, forks, topics
MAX_COMMITS = int(os.environ.get("CODEDNA_MAX_COMMITS", "2000"))
MAX_FILES = int(os.environ.get("CODEDNA_MAX_FILES", "3000"))
# Worker processes / threads for big repositories (1 turns parallel mode off; results do not change)
WORKERS = max(1, int(os.environ.get("CODEDNA_WORKERS", min(os.cpu_count() or 1, 8))))

# ---- fingerprint layout (see docs/SCHEMA.md)
DIM_METRICS = 8
DIM_LANGUAGE = 12
DIM_DEPENDENCY = 64
DIM_STRUCTURE = 16
DIM_EVOLUTION = 8
DIM_SEMANTIC = 64

# Default similarity weights; the evaluation reports how sensitive results are to these.
WEIGHTS = {
    "metrics": 0.15,
    "language": 0.15,
    "dependency": 0.20,
    "structure": 0.10,
    "evolution": 0.15,
    "semantic": 0.25,
}
