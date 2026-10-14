"""Per-file analysis: read, count lines, parse. Independent per file, so it can run in parallel.

Kept in its own module so worker processes only import what they need.
"""
from codedna.extraction.parser import parse_python
from codedna.preprocessing import count_lines


def analyze_file(item):
    """item = (path, language). Returns None if the file cannot be read."""
    path, lang = item
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    code, comments = count_lines(text)
    return {"path": path, "lang": lang, "code": code, "comments": comments,
            "parsed": parse_python(text) if lang == "Python" else None}
