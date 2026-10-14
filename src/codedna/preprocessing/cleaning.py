"""Step 3: data cleaning. Decide which files count, normalise paths, identify languages."""
import os

from codedna import config

# Folders holding vendored, generated or build output rather than the project's own code.
SKIP_DIRS = {".git", "node_modules", "vendor", "venv", ".venv", "__pycache__", "build", "dist",
             ".tox", ".mypy_cache", "site-packages", "third_party"}

# Generated or minified files that would distort size and complexity metrics.
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".lock", ".pb.go", "_pb2.py")
SKIP_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "pnpm-lock.yaml"}

LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".java": "Java", ".c": "C", ".h": "C", ".cpp": "C++",
    ".cc": "C++", ".hpp": "C++", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".cs": "C#", ".kt": "Kotlin", ".swift": "Swift", ".sh": "Shell",
    ".html": "HTML", ".css": "CSS",
}

# Fixed order so the language vector keeps one meaning (12 slots, the last is "Other").
LANG_ORDER = ["Python", "JavaScript", "TypeScript", "Java", "C", "C++", "Go",
              "Rust", "Ruby", "PHP", "C#", "Other"]


def normalize_path(path: str, root: str) -> str:
    """Path relative to the repository root with forward slashes, on any operating system."""
    return os.path.relpath(path, root).replace(os.sep, "/")


def detect_language(path: str):
    """Programming language from the file extension, or None if it is not a source file."""
    return LANG_BY_EXT.get(os.path.splitext(path)[1].lower())


def is_ignored(name: str) -> bool:
    """True for generated, minified and lock files."""
    return name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES)


def walk_files(root: str):
    """Yield the project's own files under root, up to MAX_FILES."""
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in filenames:
            if is_ignored(name):
                continue
            yield os.path.join(dirpath, name)
            n += 1
            if n >= config.MAX_FILES:
                return


def count_lines(text: str):
    """Return (code_lines, comment_lines). A line starting with #, //, /* or * is a comment."""
    code = comments = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(("#", "//", "/*", "*")):
            comments += 1
        else:
            code += 1
    return code, comments
