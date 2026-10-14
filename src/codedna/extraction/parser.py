"""Step 3: code parsing. Python files are parsed with the standard ast module."""
import ast
import warnings
from collections import deque

from radon.complexity import cc_visit_ast


def _base_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def parse_python(text: str):
    """Parse one Python file (once).

    Returns a dict with classes (name and base names), function names, top-level imported
    modules, the set of (caller, callee) pairs and per-function cyclomatic complexities.
    Returns None if the file does not parse.

    One breadth-first pass collects everything. `chain` holds the names of the functions
    enclosing a node, so a call inside a nested function counts for every function around it.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # cloned code may contain old escape sequences
            tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None

    classes, functions, imports, calls = [], [], set(), set()
    queue = deque([(tree, ())])
    pop, push = queue.popleft, queue.extend
    iter_children = ast.iter_child_nodes
    ClassDef, FunctionDef, AsyncFunctionDef = ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef
    Call, Import, ImportFrom = ast.Call, ast.Import, ast.ImportFrom
    while queue:
        node, chain = pop()
        kind = type(node)
        if kind is ClassDef:
            classes.append({"name": node.name,
                            "bases": [b for b in (_base_name(x) for x in node.bases) if b]})
        elif kind is FunctionDef or kind is AsyncFunctionDef:
            functions.append(node.name)
            chain = chain + (node.name,)
        elif kind is Call:
            if chain:
                callee = _base_name(node.func)
                if callee:
                    for caller in chain:
                        calls.add((caller, callee))
        elif kind is Import:
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif kind is ImportFrom:
            if node.level == 0 and node.module:  # level > 0 means a relative import
                imports.add(node.module.split(".")[0])
        push([(child, chain) for child in iter_children(node)])

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            complexities = [b.complexity for b in cc_visit_ast(tree)]
    except Exception:
        complexities = []

    return {"classes": classes, "functions": functions, "imports": sorted(imports),
            "calls": sorted(calls), "complexities": complexities}


def inheritance_depths(classes: list) -> list:
    """Inheritance depth of each class, following only base classes defined in the same repo."""
    bases = {c["name"]: c["bases"] for c in classes}
    memo = {}

    def depth(name, seen=()):
        if name in memo:
            return memo[name]
        if name in seen or name not in bases:
            return 0
        d = 0
        for b in bases[name]:
            if b in bases:
                d = max(d, 1 + depth(b, seen + (name,)))
        memo[name] = d
        return d

    return [depth(n) for n in bases]
