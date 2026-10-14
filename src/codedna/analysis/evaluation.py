"""Similarity evaluation for the paper.

Question: does the Code DNA fingerprint retrieve repositories of the same kind?
Ground truth is datasets/labels.csv (one category per repository). Each repository is a
query: rank all the others and measure how many of the top results share its category.

Compared against: single groups, leave-one-group-out, equal weights, a README TF-IDF text
baseline, a package-Jaccard baseline and random ranking. Also reports how sensitive the
result is to the weights.
"""
import csv
import json
import os

import numpy as np

from codedna import config
from codedna.analysis.similarity import GROUPS, Corpus

KS = (1, 3, 5)


def load_inputs(results_dir: str = None, labels_path: str = None):
    """Fingerprints and READMEs exported by the pipeline, plus the category labels."""
    results_dir = results_dir or config.RESULTS_DIR
    labels_path = labels_path or os.path.join(config.DATASETS_DIR, "labels.csv")
    with open(os.path.join(results_dir, "fingerprints.json")) as f:
        fps = json.load(f)
    with open(os.path.join(results_dir, "readmes.json")) as f:
        readmes = json.load(f)
    with open(labels_path) as f:
        labels = {r["repo"]: r["category"] for r in csv.DictReader(f)}
    fps = sorted((x for x in fps if x["repo_id"] in labels), key=lambda x: x["repo_id"])
    return fps, readmes, labels


def rank_metrics(scores: np.ndarray, ids: list, labels: dict, ks=KS):
    """Precision@k, MRR and MAP averaged over every repository that has at least one
    same-category peer. Returns (metrics, number_of_queries). For small categories k is
    capped at the number of relevant items so they are not penalised."""
    n = len(ids)
    cats = [labels[i] for i in ids]
    out = {f"P@{k}": [] for k in ks}
    out["MRR"], out["MAP"] = [], []
    for q in range(n):
        relevant = sum(1 for j in range(n) if j != q and cats[j] == cats[q])
        if relevant == 0:
            continue
        order = [j for j in np.argsort(-scores[q], kind="stable") if j != q]
        hits = [cats[j] == cats[q] for j in order]
        for k in ks:
            kk = min(k, relevant)
            out[f"P@{k}"].append(sum(hits[:kk]) / kk)
        first = next((r for r, h in enumerate(hits, 1) if h), None)
        out["MRR"].append(1.0 / first if first else 0.0)
        found, ap = 0, 0.0
        for r, h in enumerate(hits, 1):
            if h:
                found += 1
                ap += found / r
        out["MAP"].append(ap / relevant)
    return {k: round(float(np.mean(v)), 4) for k, v in out.items()}, len(out["MRR"])


def random_baseline(ids, labels, trials=200, seed=0) -> dict:
    rng = np.random.default_rng(seed)
    runs = [rank_metrics(rng.random((len(ids), len(ids))), ids, labels)[0] for _ in range(trials)]
    return {k: round(float(np.mean([r[k] for r in runs])), 4) for k in runs[0]}


def tfidf_matrix(ids, readmes) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = [readmes.get(i, "") or "" for i in ids]
    x = TfidfVectorizer(stop_words="english", max_features=5000, sublinear_tf=True).fit_transform(docs)
    return (x @ x.T).toarray()


def jaccard_matrix(fps) -> np.ndarray:
    sets = [set(f["packages"]) for f in fps]
    return np.array([[len(a & b) / max(len(a | b), 1) for b in sets] for a in sets])


def weight_sensitivity(corpus, ids, labels, samples=300, seed=42) -> dict:
    """MAP under random weightings drawn uniformly from the simplex."""
    rng = np.random.default_rng(seed)
    maps = []
    for _ in range(samples):
        w = dict(zip(GROUPS, rng.dirichlet(np.ones(len(GROUPS)))))
        maps.append(rank_metrics(corpus.score_matrix(w), ids, labels)[0]["MAP"])
    return {"samples": samples, "MAP_mean": round(float(np.mean(maps)), 4),
            "MAP_std": round(float(np.std(maps)), 4), "MAP_min": round(float(np.min(maps)), 4),
            "MAP_max": round(float(np.max(maps)), 4)}


def top1_confusion(corpus, ids, labels) -> dict:
    """(true category, category of the top-1 neighbour) -> count."""
    sm = corpus.score_matrix()
    conf = {}
    for q, rid in enumerate(ids):
        j = next(x for x in np.argsort(-sm[q], kind="stable") if x != q)
        key = (labels[rid], labels[ids[j]])
        conf[key] = conf.get(key, 0) + 1
    return conf


def run_evaluation(fps, readmes, labels) -> dict:
    ids = [f["repo_id"] for f in fps]
    corpus = Corpus([{"repo_id": f["repo_id"], "packages": f["packages"],
                      "raw_vectors": f["raw_vectors"]} for f in fps])
    rows = []

    def add(name, matrix, family):
        m, n_queries = rank_metrics(matrix, ids, labels)
        rows.append({"method": name, "family": family, **m, "queries": n_queries})

    default = dict(config.WEIGHTS)
    add("Code DNA (all 6 groups, default weights)", corpus.score_matrix(default), "full")
    add("Code DNA (all 6 groups, equal weights)", corpus.score_matrix({g: 1.0 / len(GROUPS) for g in GROUPS}), "full")
    for g in GROUPS:
        add(f"only {g}", corpus.score_matrix({h: float(h == g) for h in GROUPS}), "single group")
    for g in GROUPS:
        w = {h: (0.0 if h == g else default[h]) for h in GROUPS}
        s = sum(w.values())
        add(f"without {g}", corpus.score_matrix({h: v / s for h, v in w.items()}), "leave one out")
    add("README TF-IDF (text baseline)", tfidf_matrix(ids, readmes), "baseline")
    add("Package Jaccard (dependency-only baseline)", jaccard_matrix(fps), "baseline")
    rows.append({"method": "Random ranking (mean of 200 trials)", "family": "baseline",
                 **random_baseline(ids, labels), "queries": rows[0]["queries"]})

    sens = weight_sensitivity(corpus, ids, labels)
    sens["default_weights_MAP"] = rows[0]["MAP"]
    return {"repositories": len(ids), "categories": len({labels[i] for i in ids}),
            "rows": rows, "sensitivity": sens, "confusion": top1_confusion(corpus, ids, labels)}


def write_outputs(result: dict, results_dir: str = None):
    """Write similarity_eval.csv/json, weight_sensitivity.json and confusion_by_category.csv."""
    results_dir = results_dir or config.RESULTS_DIR
    os.makedirs(results_dir, exist_ok=True)
    rows = result["rows"]
    with open(os.path.join(results_dir, "similarity_eval.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(results_dir, "similarity_eval.json"), "w") as f:
        json.dump({"repositories": result["repositories"], "categories": result["categories"],
                   "rows": rows}, f, indent=2)
    with open(os.path.join(results_dir, "weight_sensitivity.json"), "w") as f:
        json.dump(result["sensitivity"], f, indent=2)
    with open(os.path.join(results_dir, "confusion_by_category.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["true_category", "top1_neighbour_category", "count"])
        for (a, b), c in sorted(result["confusion"].items()):
            w.writerow([a, b, c])


def format_table(result: dict) -> str:
    lines = [f"{'method':48s} {'P@1':>6} {'P@3':>6} {'P@5':>6} {'MRR':>6} {'MAP':>6}"]
    for r in result["rows"]:
        lines.append(f"{r['method']:48s} {r['P@1']:6.3f} {r['P@3']:6.3f} {r['P@5']:6.3f} "
                     f"{r['MRR']:6.3f} {r['MAP']:6.3f}")
    return "\n".join(lines)
