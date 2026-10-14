# Code DNA

A hybrid NoSQL framework that turns a software repository into a structured profile, its
**Code DNA**, and stores each part of that profile in the database model that suits it.
Repositories can then be searched, compared and analysed.

This is a research prototype of the architecture and method. It is not a production system
and not a GitHub clone.

## The idea

A repository is more than source code: it has metadata, history, contributors, dependencies,
call relationships and documentation. These are different kinds of data. Forcing them all
into one database is a poor fit, so Code DNA sends each kind to the store that handles it best.

| Data | Store | Why |
|---|---|---|
| Metadata, README, config, per-file summaries, structure | MongoDB (document) | JSON with a flexible schema |
| Dependency, import, call and contributor graphs | Neo4j (graph) | Relationships and traversals |
| Metrics, repository statistics, commit history, time series | Cassandra (wide column) | Wide numeric rows and large time-ordered data |
| Repository ID index, lookup features, query cache | Redis (key-value) | Fast lookups |

The choice is made by a rule, not by hand (`src/codedna/dna/classifier.py`). Run
`python -m codedna mapping` to print the result.

## Pipeline

```
Repository -> Collection -> Parsing -> Preprocessing -> Feature extraction
           -> Code DNA generation -> Classification -> Hybrid NoSQL storage
           -> Query engine -> Similarity analysis -> Results
```

The Code DNA fingerprint has six parts: code metrics, language mix, dependencies, folder
structure, evolution (commit history) and semantics (README and identifier words). Two
repositories are compared by a weighted sum of the cosine similarity of each part. The full
layout is in `docs/SCHEMA.md`.

## Quick start

You need Python 3.11 or newer, git and Docker.

```
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell (cmd: .venv\Scripts\activate). macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d              # MongoDB, Neo4j, Redis, Cassandra
docker compose ps                 # wait until all four say "healthy" (Cassandra takes ~1 minute)

pytest                            # unit tests, no databases needed
```

Then the same storage checks against the real databases:

```
$env:CODEDNA_TEST_REAL = "1"      # Windows PowerShell (cmd: set CODEDNA_TEST_REAL=1; macOS/Linux: export CODEDNA_TEST_REAL=1)
pytest tests/test_storage_contract.py
```

The real-database tests wipe the databases they connect to. They only run when
`CODEDNA_TEST_REAL=1` is set.

## Running the study

```
python -m codedna ingest --fresh   # collect the 30 repositories in datasets/repos.txt
python -m codedna evaluate         # similarity evaluation, writes results/*.csv and *.json
python -m codedna benchmark        # hybrid store against a MongoDB-only baseline
python -m codedna serve            # REST API at http://127.0.0.1:8000/docs
```

Queries from the command line:

```
python -m codedna query similar_to repo_id=pallets/flask k=3
python -m codedna query using_technology technology=react
python -m codedna query high_complexity threshold=6
python -m codedna query similar_dependencies repo_id=psf/requests
python -m codedna query contributors_of repo_id=pallets/click
```

Large repositories are processed in parallel (set `CODEDNA_WORKERS=1` to turn that off; results
are identical either way). If you call the library from your own script on Windows, put your code
under `if __name__ == "__main__":`.

Cloned repositories take about 1 GB. Set `CODEDNA_DATA` (see `.env.example`) to a folder
outside OneDrive or Dropbox, because sync tools slow git down.

## What the evaluation measures

`evaluate` ranks, for each repository, all the others by Code DNA similarity and checks how
many of the top results share its category in `datasets/labels.csv`. It reports precision,
MRR and MAP, and compares against single fingerprint parts, leave-one-part-out, equal
weights, a README text baseline, a package-overlap baseline and random ranking. It also
shows how much the result depends on the weights.

`benchmark` loads the same data into the hybrid store and into MongoDB alone, checks that
both give identical answers to the five queries, then times them.

## Project layout

```
src/codedna/
  collection/     step 1   clone repositories, read history and metadata
  preprocessing/  step 3   cleaning, language detection, tokenising
  extraction/     steps 2, 4   parsing and feature extraction
  dna/            steps 5-7    fingerprint vectors, Code DNA record, storage mapping
  storage/        step 8   four database backends and the unified access layer
  query/          step 9   the query engine
  analysis/       steps 10-11  similarity and evaluation
  benchmark/      step 11  hybrid against a single-database baseline
  api/            REST API
  pipeline.py, cli.py
datasets/         repository list and category labels
docs/SCHEMA.md    the Code DNA schema
tests/            unit and contract tests
```

## Known limits

- Only Python is parsed in depth (call graph, complexity, inheritance). Repositories in other
  languages get line counts, structure, dependencies from their manifests and history.
- The semantic part is a hashed bag of words, not a neural embedding. It can be replaced with
  sentence-transformers without changing the rest of the pipeline.
- Only the newest 2,000 commits of each repository are read for history features. The real
  total is stored next to them.
- Category labels in `datasets/labels.csv` were assigned by hand.
- Pull request counts and stars need a `GITHUB_TOKEN`.
