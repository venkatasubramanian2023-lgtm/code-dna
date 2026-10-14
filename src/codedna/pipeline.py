"""Steps 1-8 end to end: collect, parse, extract, generate DNA, classify, store.

Also exports what the evaluation needs (fingerprints.json, readmes.json) and a log of
timings per repository (ingest_log.json), so the paper's numbers can be reproduced.
"""
import json
import os
import time

from codedna import config
from codedna.collection import github
from codedna.dna import generate


def read_repo_list(path: str) -> list:
    """One owner/name per line; blank lines and lines starting with # are ignored."""
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]


def ingest_repo(full_name: str, store, collect=github.collect) -> dict:
    """Run one repository through the whole pipeline. Returns the DNA and per-stage timings."""
    t0 = time.perf_counter()
    collected = collect(full_name)
    t1 = time.perf_counter()
    dna = generate(collected)
    t2 = time.perf_counter()
    by_db = store.ingest(dna)
    t3 = time.perf_counter()
    return {"dna": dna, "collect_s": round(t1 - t0, 3), "dna_s": round(t2 - t1, 3),
            "store_s": round(t3 - t2, 3), "store_by_db_s": by_db}


def run(repos: list, store, fresh: bool = False, results_dir: str = None, progress=print,
        collect=github.collect) -> list:
    """Ingest every repository; one failure is recorded and does not stop the run."""
    results_dir = results_dir or config.RESULTS_DIR
    os.makedirs(results_dir, exist_ok=True)
    if fresh:
        store.clear_all()
    log, fingerprints, readmes = [], [], {}
    for i, name in enumerate(repos, 1):
        row = {"repo": name}
        try:
            r = ingest_repo(name, store, collect)
            d = r["dna"]
            row.update({"status": "ok", "collect_s": r["collect_s"], "dna_s": r["dna_s"],
                        "store_s": r["store_s"], "store_by_db_s": r["store_by_db_s"],
                        "loc": d["metrics"]["total_loc"], "files": d["metrics"]["files"],
                        "commits": d["evolution_summary"]["commits"],
                        "total_commits": d["metadata"]["total_commits"],
                        "packages": len(d["packages"]), "call_edges": len(d["call_edges"]),
                        "contributors": d["evolution_summary"]["authors"],
                        "main_language": max(d["language_share"], key=d["language_share"].get)})
            fingerprints.append({"repo_id": d["repo_id"], "packages": d["packages"],
                                 "raw_vectors": d["raw_vectors"], "metrics": d["metrics"],
                                 "evolution_summary": d["evolution_summary"]})
            readmes[d["repo_id"]] = d["readme"]
            progress(f"[{i}/{len(repos)}] {name:36s} ok  loc={row['loc']:>8} "
                     f"commits={row['total_commits']:>6} {r['collect_s'] + r['dna_s'] + r['store_s']:6.1f}s")
        except Exception as exc:          # record the failure and keep going
            row.update({"status": "failed", "error": str(exc)[:300]})
            progress(f"[{i}/{len(repos)}] {name:36s} FAILED {str(exc)[:100]}")
        log.append(row)

    with open(os.path.join(results_dir, "ingest_log.json"), "w") as f:
        json.dump({"backends": store.backends, "rows": log}, f, indent=2)
    with open(os.path.join(results_dir, "fingerprints.json"), "w") as f:
        json.dump(fingerprints, f)
    with open(os.path.join(results_dir, "readmes.json"), "w") as f:
        json.dump(readmes, f)
    return log
