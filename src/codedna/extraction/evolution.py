"""Evolution features from the commit history: monthly time series and summary numbers."""
from collections import Counter, defaultdict


def evolution_features(commits: list) -> dict:
    """`commits` is newest first, as returned by the collector."""
    monthly = defaultdict(lambda: {"commits": 0, "insertions": 0, "deletions": 0, "authors": set()})
    authors = Counter()
    for c in commits:
        m = monthly[c["time"].strftime("%Y-%m")]
        m["commits"] += 1
        m["insertions"] += c["insertions"]
        m["deletions"] += c["deletions"]
        m["authors"].add(c["author"])
        authors[c["author"]] += 1

    series = [{"month": k, "commits": v["commits"], "churn": v["insertions"] + v["deletions"],
               "active_authors": len(v["authors"])} for k, v in sorted(monthly.items())]
    n = len(commits)
    span_days = max((commits[0]["time"] - commits[-1]["time"]).days, 1) if n > 1 else 1
    top_share = authors.most_common(1)[0][1] / n if n else 0.0
    return {
        "series": series,
        "summary": {
            "commits": n,
            "authors": len(authors),
            "span_days": span_days,
            "commits_per_month": round(n / max(span_days / 30.0, 1.0), 3),
            "total_churn": sum(s["churn"] for s in series),
            "top_author_share": round(top_share, 4),
            "avg_files_per_commit": round(sum(c["files_changed"] for c in commits) / max(n, 1), 3),
        },
        "author_counts": dict(authors),
    }
