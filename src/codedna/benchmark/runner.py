"""Step 11: performance evaluation. Hybrid store against a MongoDB-only baseline.

Measures, on the same Code DNA records:
  1. ingest time (hybrid broken down by database)
  2. whether both systems give the SAME answer to each query (a speed comparison means
     nothing if the answers differ)
  3. query latency (median, p95, mean) for the five template queries
  4. how many bytes of Code DNA are routed to each database
"""
import csv
import json
import os
import random
import time
from collections import Counter

import numpy as np

from codedna import config
from codedna.dna.classifier import route
from codedna.query import QueryEngine


def _ms(fn, *args, **kwargs):
    t = time.perf_counter()
    result = fn(*args, **kwargs)
    return (time.perf_counter() - t) * 1000.0, result


def _stats(samples):
    a = np.array(samples)
    return {"n": len(a), "median_ms": round(float(np.median(a)), 3),
            "p95_ms": round(float(np.percentile(a, 95)), 3), "mean_ms": round(float(a.mean()), 3)}


def _norm(results):
    """Drop fields that legitimately differ between systems (float noise is rounded)."""
    return json.loads(json.dumps(results, default=lambda x: round(x, 4)))


def ingest_all(dnas, hybrid, baseline) -> dict:
    per_db, base = Counter(), 0.0
    for d in dnas:
        for db, seconds in hybrid.ingest(d).items():
            per_db[db] += seconds
        base += baseline.ingest(d)
    return {"hybrid_total_s": round(sum(per_db.values()), 3),
            "hybrid_by_database_s": {k: round(v, 3) for k, v in per_db.items()},
            "baseline_total_s": round(base, 3)}


def check_agreement(dnas, engine, baseline) -> dict:
    """Run every query on both systems and count how often the answers are identical."""
    ids = [d["repo_id"] for d in dnas]
    pkg_counts = Counter(p for d in dnas for p in d["packages"])
    techs = [p for p, _ in pkg_counts.most_common(8)]
    avg = sorted(d["metrics"]["avg_cyclomatic"] for d in dnas)
    thresholds = [avg[len(avg) // 4], avg[len(avg) // 2], avg[3 * len(avg) // 4]]
    checks = {"using_technology": [], "high_complexity": [], "similar_dependencies": [],
              "contributors_of": [], "similar_to": []}

    for t in techs:
        checks["using_technology"].append(engine.using_technology(t)["results"] == baseline.using_technology(t))
    for th in thresholds:
        checks["high_complexity"].append(
            _norm(engine.high_complexity(th, top=100)["results"]) == _norm(baseline.high_complexity(th, 100)))
    for r in ids:
        h = engine.similar_dependencies(r, 5)["results"]
        b = baseline.similar_dependencies(r, 5)
        checks["similar_dependencies"].append(_norm(h) == _norm(b))
        checks["contributors_of"].append(
            _norm(engine.contributors_of(r, 10)["results"]) == _norm(baseline.contributors_of(r, 10)))
        checks["similar_to"].append(_norm(engine.similar_to(r, 5)["results"]) == _norm(baseline.similar_to(r, 5)))
    return {q: {"checked": len(v), "identical": sum(v)} for q, v in checks.items()}


def measure_latency(dnas, hybrid, baseline, repeats=30, seed=0) -> list:
    rng = random.Random(seed)
    engine = QueryEngine(hybrid)
    ids = [d["repo_id"] for d in dnas]
    sample = [rng.choice(ids) for _ in range(repeats)]
    pkg_counts = Counter(p for d in dnas for p in d["packages"])
    techs = [p for p, _ in pkg_counts.most_common(5)]
    tech_sample = [techs[i % len(techs)] for i in range(repeats)]
    median_cc = sorted(d["metrics"]["avg_cyclomatic"] for d in dnas)[len(dnas) // 2]

    rows = []

    def add(query, system, samples):
        rows.append({"query": query, "system": system, **_stats(samples)})

    add("using_technology", "hybrid", [_ms(engine.using_technology, t)[0] for t in tech_sample])
    add("using_technology", "mongodb_only", [_ms(baseline.using_technology, t)[0] for t in tech_sample])

    add("high_complexity", "hybrid", [_ms(engine.high_complexity, median_cc)[0] for _ in range(repeats)])
    add("high_complexity", "mongodb_only", [_ms(baseline.high_complexity, median_cc)[0] for _ in range(repeats)])

    add("similar_dependencies", "hybrid", [_ms(engine.similar_dependencies, r)[0] for r in sample])
    add("similar_dependencies", "mongodb_only", [_ms(baseline.similar_dependencies, r)[0] for r in sample])

    add("contributors_of", "hybrid", [_ms(engine.contributors_of, r)[0] for r in sample])
    add("contributors_of", "mongodb_only", [_ms(baseline.contributors_of, r)[0] for r in sample])

    # similar_to: cold = no cached answer; warm = answer already in Redis
    baseline.similar_to(sample[0])                       # build the in-process corpus once
    cold = []
    for r in sample:
        hybrid.redis.clear_cache()
        cold.append(_ms(engine.similar_to, r)[0])
    add("similar_to (cold)", "hybrid", cold)
    for r in set(sample):
        engine.similar_to(r)
    add("similar_to (warm, Redis cache)", "hybrid", [_ms(engine.similar_to, r)[0] for r in sample])
    add("similar_to", "mongodb_only", [_ms(baseline.similar_to, r)[0] for r in sample])
    return rows


def routed_bytes(dnas) -> dict:
    """Bytes of Code DNA that the classifier sends to each database."""
    sizes = Counter()
    for d in dnas:
        for db, part in route(d).items():
            sizes[db] += len(json.dumps(part, default=str))
    total = sum(sizes.values()) or 1
    return {db: {"bytes": sizes[db], "share": round(sizes[db] / total, 4)}
            for db in ("mongodb", "neo4j", "cassandra", "redis")}


def run_benchmark(dnas, hybrid, baseline, repeats=30, seed=0, progress=print) -> dict:
    """`hybrid` and `baseline` must be empty; both are filled with the same records."""
    progress("ingesting into both systems ...")
    ingest = ingest_all(dnas, hybrid, baseline)
    progress("checking that both systems answer identically ...")
    agreement = check_agreement(dnas, QueryEngine(hybrid), baseline)
    progress(f"measuring latency ({repeats} repetitions per query) ...")
    latency = measure_latency(dnas, hybrid, baseline, repeats, seed)
    return {"repositories": len(dnas), "repeats": repeats, "seed": seed, "backends": hybrid.backends,
            "ingest": ingest, "agreement": agreement, "latency": latency, "routed_bytes": routed_bytes(dnas)}


def write_outputs(result: dict, results_dir: str = None):
    results_dir = results_dir or config.RESULTS_DIR
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "benchmark.json"), "w") as f:
        json.dump(result, f, indent=2)
    with open(os.path.join(results_dir, "benchmark.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["query", "system", "n", "median_ms", "p95_ms", "mean_ms"])
        w.writeheader()
        w.writerows(result["latency"])


def format_report(result: dict) -> str:
    lines = [f"{result['repositories']} repositories, {result['repeats']} repetitions per query",
             f"backends: {result['backends']}", "",
             "ingest (s): " + json.dumps(result["ingest"]), "", "answers identical on both systems:"]
    for q, a in result["agreement"].items():
        lines.append(f"  {q:24s} {a['identical']}/{a['checked']}")
    lines += ["", f"{'query':34s} {'system':14s} {'median ms':>10} {'p95 ms':>10} {'mean ms':>10}"]
    for r in result["latency"]:
        lines.append(f"{r['query']:34s} {r['system']:14s} {r['median_ms']:10.3f} {r['p95_ms']:10.3f} {r['mean_ms']:10.3f}")
    lines += ["", "bytes of Code DNA routed to each database:"]
    for db, v in result["routed_bytes"].items():
        lines.append(f"  {db:10s} {v['bytes']:>12,}  ({v['share']:.1%})")
    return "\n".join(lines)
