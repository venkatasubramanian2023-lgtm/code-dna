"""Command line: python -m codedna <command>

  ingest     collect repositories and store their Code DNA in the four databases
  evaluate   similarity evaluation (needs results/ from a previous ingest)
  query      run one of the queries, for example: query using_technology technology=flask
  benchmark  hybrid store against a MongoDB-only baseline (clears the databases first)
  mapping    print which database each feature group is stored in
  serve      start the REST API
"""
import argparse
import json
import os
import sys

from codedna import config


def _parse_params(items):
    """['k=3', 'name=flask'] -> {'k': 3, 'name': 'flask'} (numbers become numbers)."""
    out = {}
    for item in items:
        key, _, value = item.partition("=")
        if not key or not _:
            raise SystemExit(f"parameter must look like key=value, got {item!r}")
        for cast in (int, float):
            try:
                value = cast(value)
                break
            except ValueError:
                continue
        out[key] = value
    return out


def cmd_ingest(args):
    from codedna import pipeline
    from codedna.storage import HybridStore
    repos = pipeline.read_repo_list(args.repo_list)
    if args.limit:
        repos = repos[:args.limit]
    store = HybridStore()
    print("Back ends:", store.backends)
    log = pipeline.run(repos, store, fresh=args.fresh)
    ok = sum(1 for r in log if r["status"] == "ok")
    print(f"Done: {ok}/{len(log)} repositories stored. Exports are in {config.RESULTS_DIR}/")
    return 0 if ok == len(log) else 1


def cmd_evaluate(args):
    from codedna.analysis import evaluation
    fps, readmes, labels = evaluation.load_inputs(args.results, args.labels)
    result = evaluation.run_evaluation(fps, readmes, labels)
    evaluation.write_outputs(result, args.results)
    print(f"{result['repositories']} repositories, {result['categories']} categories\n")
    print(evaluation.format_table(result))
    print("\nWeight sensitivity:", result["sensitivity"])
    return 0


def cmd_query(args):
    from codedna.query import QueryEngine
    from codedna.storage import HybridStore
    answer = QueryEngine(HybridStore()).run(args.name, **_parse_params(args.params))
    print(json.dumps(answer, indent=2, default=str))
    return 0


def cmd_benchmark(args):
    from pymongo import MongoClient

    from codedna import pipeline
    from codedna.benchmark import SingleStoreBaseline, run_benchmark
    from codedna.benchmark.runner import format_report, write_outputs
    from codedna.collection import github
    from codedna.dna import generate
    from codedna.storage import HybridStore

    repos = pipeline.read_repo_list(args.repo_list)
    if args.limit:
        repos = repos[:args.limit]
    hybrid = HybridStore()
    baseline = SingleStoreBaseline(MongoClient(config.MONGO_URI)[config.MONGO_DB + "_baseline"])
    print("Back ends:", hybrid.backends, "\nThis clears all four databases and the baseline database.")
    hybrid.clear_all()
    baseline.clear()
    dnas = []
    for i, name in enumerate(repos, 1):
        try:
            dnas.append(generate(github.collect(name)))
            print(f"[{i}/{len(repos)}] {name} collected")
        except Exception as exc:
            print(f"[{i}/{len(repos)}] {name} FAILED {str(exc)[:100]}")
    result = run_benchmark(dnas, hybrid, baseline, repeats=args.repeats)
    write_outputs(result, args.results)
    print("\n" + format_report(result))
    return 0


def cmd_mapping(_args):
    from codedna.dna.classifier import mapping
    for feature, db in mapping().items():
        print(f"{feature:20s} -> {db}")
    return 0


def cmd_serve(args):
    import uvicorn
    uvicorn.run("codedna.api.app:create_app", factory=True, host=args.host, port=args.port)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="codedna", description="Code DNA: hybrid NoSQL repository analysis")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("ingest", help="collect repositories and store their Code DNA")
    s.add_argument("repo_list", nargs="?", default=os.path.join(config.DATASETS_DIR, "repos.txt"))
    s.add_argument("--limit", type=int, help="only the first N repositories")
    s.add_argument("--fresh", action="store_true", help="clear all four databases first")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("evaluate", help="similarity evaluation for the paper")
    s.add_argument("--results", default=config.RESULTS_DIR)
    s.add_argument("--labels", default=os.path.join(config.DATASETS_DIR, "labels.csv"))
    s.set_defaults(func=cmd_evaluate)

    s = sub.add_parser("query", help="run a query")
    s.add_argument("name", help="similar_to, using_technology, high_complexity, "
                                "similar_dependencies, contributors_of, by_language, search_readme")
    s.add_argument("params", nargs="*", help="key=value pairs, for example repo_id=pallets/flask k=3")
    s.set_defaults(func=cmd_query)

    s = sub.add_parser("benchmark", help="hybrid store against a MongoDB-only baseline")
    s.add_argument("repo_list", nargs="?", default=os.path.join(config.DATASETS_DIR, "repos.txt"))
    s.add_argument("--limit", type=int, help="only the first N repositories")
    s.add_argument("--repeats", type=int, default=30, help="repetitions per query")
    s.add_argument("--results", default=config.RESULTS_DIR)
    s.set_defaults(func=cmd_benchmark)

    s = sub.add_parser("mapping", help="print the feature group to database mapping")
    s.set_defaults(func=cmd_mapping)

    s = sub.add_parser("serve", help="start the REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:        # for example: databases not running
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
