"""Declared dependencies read from manifests, and third-party imports found in code."""
import json
import re
import sys
from collections import Counter

STDLIB = set(getattr(sys, "stdlib_module_names", set()))
_REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _norm(name: str) -> str:
    return name.lower().replace("_", "-")


def parse_dependencies(dep_files: dict) -> set:
    """Package names declared in requirements.txt, pyproject.toml, setup.py or package.json."""
    pkgs = set()
    for name, text in dep_files.items():
        if name == "requirements.txt":
            for line in text.splitlines():
                line = line.split("#")[0].strip()
                if line and not line.startswith(("-", "git+", "http")):
                    m = _REQ_RE.match(line)
                    if m:
                        pkgs.add(_norm(m.group(1)))
        elif name == "package.json":
            try:
                data = json.loads(text)
            except ValueError:
                continue
            for key in ("dependencies", "devDependencies"):
                pkgs.update(k.lower() for k in data.get(key, {}))
        elif name == "pyproject.toml":
            pkgs |= _from_pyproject(text)
        elif name == "setup.py":
            block = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.S)
            for spec in re.findall(r"""["']([^"']+)["']""", block.group(1)) if block else []:
                m = _REQ_RE.match(spec)
                if m:
                    pkgs.add(_norm(m.group(1)))
    return pkgs


def _from_pyproject(text: str) -> set:
    try:
        import tomllib
        data = tomllib.loads(text)
    except Exception:
        return set()
    specs = list(data.get("project", {}).get("dependencies", []))
    for group in data.get("project", {}).get("optional-dependencies", {}).values():
        specs.extend(group)
    for group in data.get("dependency-groups", {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    specs.extend(data.get("build-system", {}).get("requires", []))
    specs.extend(data.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
    out = set()
    for spec in specs:
        m = _REQ_RE.match(spec)
        if m and m.group(1).lower() != "python":
            out.add(_norm(m.group(1)))
    return out


def third_party_imports(imports_by_file: dict, file_paths: list) -> dict:
    """Count, per module, in how many files it is imported, ignoring the standard library
    and anything named like a file or folder inside the repository."""
    import os
    local = set()
    for path in file_paths:
        parts = path.split("/")
        local.add(os.path.splitext(parts[-1])[0])
        local.update(parts[:-1])
    counts = Counter()
    for imports in imports_by_file.values():
        for module in imports:
            if module not in STDLIB and module not in local:
                counts[module.lower()] += 1
    return dict(counts)
