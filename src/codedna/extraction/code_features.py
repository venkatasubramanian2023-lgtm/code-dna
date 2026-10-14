"""Step 4: feature extraction from the files of one repository."""
import multiprocessing
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from codedna import config
from codedna.extraction.analyzer import analyze_file
from codedna.extraction.dependencies import third_party_imports
from codedna.extraction.parser import inheritance_depths
from codedna.extraction.structure import structure_features
from codedna.preprocessing import LANG_ORDER, detect_language, normalize_path, walk_files

PARALLEL_MIN_FILES = 300      # below this, starting worker processes costs more than it saves


def _analyze_all(items: list, workers: int, min_files: int = None) -> list:
    """Analyze every (path, language) item, in order. Uses worker processes for big repositories
    and falls back to a plain loop if they cannot be started."""
    min_files = PARALLEL_MIN_FILES if min_files is None else min_files
    python_files = sum(1 for _, lang in items if lang == "Python")
    # never start a pool from inside a worker: a script without an `if __name__ == "__main__"`
    # guard is re-run by each spawned worker, which would otherwise multiply without end
    in_worker = multiprocessing.parent_process() is not None
    if workers > 1 and python_files >= min_files and not in_worker:
        try:
            # "spawn" behaves the same on Windows, macOS and Linux
            with ProcessPoolExecutor(max_workers=workers,
                                     mp_context=multiprocessing.get_context("spawn")) as pool:
                return list(pool.map(analyze_file, items, chunksize=32))
        except Exception:
            pass
    return [analyze_file(item) for item in items]


def extract_code_features(root: str, workers: int = None, parallel_min_files: int = None) -> dict:
    """Walk the repository once. Returns metrics, language share, per-file documents,
    imports, call-graph edges, third-party import counts and structure features.

    `workers` is the number of processes (default: CODEDNA_WORKERS or the CPU count, at most 8;
    1 disables parallel mode). The result does not depend on it.
    """
    workers = workers or config.WORKERS
    items = [(p, lang) for p in walk_files(root) if (lang := detect_language(p)) is not None]

    lang_loc = Counter()
    file_docs, all_classes, all_funcs = [], [], set()
    complexities, imports_by_file, call_edges = [], {}, set()
    total_code = total_comments = 0

    for res in _analyze_all(items, workers, parallel_min_files):
        if res is None:
            continue
        lang = res["lang"]
        total_code += res["code"]
        total_comments += res["comments"]
        lang_loc[lang if lang in LANG_ORDER else "Other"] += res["code"]
        rel = normalize_path(res["path"], root)
        doc = {"path": rel, "language": lang, "loc": res["code"]}
        parsed = res["parsed"]
        if parsed:
            doc.update({"classes": [c["name"] for c in parsed["classes"]],
                        "functions": parsed["functions"], "imports": parsed["imports"]})
            all_classes.extend(parsed["classes"])
            all_funcs.update(parsed["functions"])
            complexities.extend(parsed["complexities"])
            imports_by_file[rel] = parsed["imports"]
            call_edges.update(parsed["calls"])
        file_docs.append(doc)

    # keep call edges whose target is defined in the repository; drop self-calls
    call_edges = sorted((a, b) for a, b in call_edges if b in all_funcs and a != b)[:5000]
    depths = inheritance_depths(all_classes)
    metrics = {
        "files": len(file_docs),
        "total_loc": total_code,
        "comment_ratio": round(total_comments / max(total_code + total_comments, 1), 4),
        "functions": len(all_funcs),
        "classes": len(all_classes),
        "avg_cyclomatic": round(sum(complexities) / len(complexities), 3) if complexities else 0.0,
        "max_cyclomatic": max(complexities) if complexities else 0,
        "avg_inheritance_depth": round(sum(depths) / len(depths), 3) if depths else 0.0,
    }
    total_lang = sum(lang_loc.values()) or 1
    return {
        "metrics": metrics,
        "language_share": {l: round(lang_loc.get(l, 0) / total_lang, 4) for l in LANG_ORDER},
        "file_docs": file_docs,
        "imports_by_file": imports_by_file,
        "call_edges": call_edges,
        "third_party_imports": third_party_imports(imports_by_file, [d["path"] for d in file_docs]),
        "structure": structure_features(root),
    }
