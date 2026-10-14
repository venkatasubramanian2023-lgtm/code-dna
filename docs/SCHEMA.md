# Code DNA schema (v0.2)

Code DNA is a structured profile of one software repository. It is not the source
code. It holds the repository's measurable characteristics, and each part is stored
in the NoSQL model that suits it. This is a research prototype of the architecture
and method, not a production system.

## Pipeline (matches the 11-step methodology)

| # | Step | Package |
|---|---|---|
| 1 | Repository collection | `collection/` |
| 2 | Repository parsing | `extraction/parser.py` |
| 3 | Data cleaning (preprocessing) | `preprocessing/` |
| 4 | Feature extraction | `extraction/` |
| 5 | Code DNA generation | `dna/generator.py`, `dna/vectors.py` |
| 6 | Feature classification | `dna/classifier.py` |
| 7 | NoSQL model mapping | `dna/classifier.py` (`mapping`, `route`) |
| 8 | Hybrid storage | `storage/` |
| 9 | Query processing | `query/` |
| 10 | Similarity analysis | `analysis/similarity.py` |
| 11 | Performance evaluation | `analysis/evaluation.py`, `benchmark/` |

## Feature groups and where they are stored

| Group | Contents | Store | Reason |
|---|---|---|---|
| metadata | owner, name, stars, forks, topics, license, age, branches, pull requests | MongoDB | JSON with a flexible schema |
| readme | README text | MongoDB | Document |
| config | dependency manifests found in the repo | MongoDB | Document |
| code_docs | per-file summary: language, LOC, classes, functions, imports | MongoDB | Nested JSON |
| structure | folder depth, presence of tests, docs, CI, setup, license | MongoDB | Extracted features, JSON |
| language_share | share of code per language | MongoDB | Extracted features, JSON |
| dependency_graph | Repo -> Package, File -> Module | Neo4j | Relationships |
| call_graph | Function -> Function | Neo4j | Relationships |
| contributor_graph | Developer -> Repo | Neo4j | Relationships |
| metrics | LOC, files, functions, classes, cyclomatic complexity, inheritance depth | Cassandra | Wide column: many numeric columns per repository |
| repo_statistics | commit count, authors, churn, bus factor | Cassandra | Wide column |
| commit_history | one row per commit | Cassandra | Large, append-only, time ordered |
| evolution_series | monthly commits, churn, active authors | Cassandra | Time series |
| lookup | repository ID index and compact feature summary | Redis | Fast key-value lookup |
| similarity_cache, repo_cache | query results | Redis | Hot, short lived |

## Storage rule (data-aware mapping)

Applied in this order, first match wins (`codedna/dna/classifier.py`):

1. Mostly about links between entities: Neo4j.
2. Wide numeric records or large time-ordered data: Cassandra.
3. Hot, read often, short lived: Redis.
4. Otherwise nested or variable in shape: MongoDB.

## Fingerprint vector

Six raw sub-vectors, each scaled across the corpus, L2 normalised and weighted. The
dot product of two fingerprints is the weighted sum of the per-group cosine
similarities.

| Sub-vector | Size | Built from |
|---|---|---|
| metrics | 8 | Log-scaled size counts, complexity, inheritance depth, comment ratio |
| language | 12 | Share of code per language |
| dependency | 64 | Hashed bag of package names (declared and imported) |
| structure | 16 | Folder-depth histogram and presence flags |
| evolution | 8 | Commit rate, churn, authors, age, bus factor |
| semantic | 64 | Hashed bag of README words and code identifier words |

The semantic vector is a dependency-free hashed bag of words. It is a stand-in for
neural embeddings (sentence-transformers) which can be swapped in later without
changing the rest of the pipeline.

## Query layer

| Query | Answered by |
|---|---|
| Repositories similar to X | fingerprints in MongoDB, cached in Redis |
| Repositories using a technology (for example React) | Neo4j package graph |
| Projects with high complexity | Cassandra metrics |
| Repositories with a similar dependency structure | Neo4j shared packages and Jaccard |
| Contributors connected to repository X | Neo4j contributor graph |
