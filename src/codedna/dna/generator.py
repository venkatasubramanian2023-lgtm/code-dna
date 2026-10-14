"""Step 5: Code DNA generation. One record per repository."""
from codedna.dna import vectors
from codedna.extraction import (evolution_features, extract_code_features, parse_dependencies,
                                semantic_tokens)

MIN_FILES_FOR_IMPORT = 2    # an import used in only one file is treated as noise


def generate(collected: dict) -> dict:
    """Turn the collector's output into a Code DNA record: every feature group plus the
    six raw sub-vectors that form the fingerprint."""
    code = extract_code_features(collected["path"])
    evo = evolution_features(collected["commits"])
    declared = parse_dependencies(collected["dependency_files"])
    imported = {p for p, n in code["third_party_imports"].items() if n >= MIN_FILES_FOR_IMPORT}
    packages = declared | imported

    full_name = collected["full_name"]
    owner, name = full_name.split("/")
    readme = collected["readme"]
    first, newest = collected.get("first_commit"), (collected["commits"] or [{}])[0].get("time")
    metadata = {
        "owner": owner, "name": name, "head": collected["head"],
        "readme_length": len(readme),
        "has_license": code["structure"]["has_license"],
        "branches": len(collected.get("branches", [])),
        "branch_names": collected.get("branches", [])[:50],
        "total_commits": collected.get("total_commits", len(collected["commits"])),
        "first_commit": first.isoformat() if first else None,
        # age is measured up to the newest commit so the value does not change with the date
        "age_days": (newest - first).days if first and newest else None,
        **collected["api"],       # stars, forks, topics, license, pull_requests (needs a token)
    }
    return {
        "repo_id": full_name,
        "metadata": metadata,
        "readme": readme,
        "config": collected["dependency_files"],
        "metrics": code["metrics"],
        "language_share": code["language_share"],
        "structure": code["structure"],
        "code_docs": code["file_docs"],
        "packages": sorted(packages),
        "package_counts": code["third_party_imports"],
        "imports_by_file": code["imports_by_file"],
        "call_edges": code["call_edges"],
        "author_counts": evo["author_counts"],
        "commits": collected["commits"],
        "evolution_series": evo["series"],
        "evolution_summary": evo["summary"],
        "raw_vectors": {
            "metrics": vectors.metrics_vector(code["metrics"]),
            "language": vectors.language_vector(code["language_share"]),
            "dependency": vectors.dependency_vector(packages),
            "structure": vectors.structure_vector(code["structure"], len(readme)),
            "evolution": vectors.evolution_vector(evo),
            "semantic": vectors.semantic_vector(semantic_tokens(readme, code["file_docs"])),
        },
    }
