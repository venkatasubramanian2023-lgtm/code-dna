"""Semantic features: the words a repository uses to describe itself and to name its code."""
from codedna.preprocessing import tokenize_identifiers, tokenize_text


def semantic_tokens(readme: str, code_docs: list) -> list:
    """README words plus words split from class and function names (documentation and code)."""
    names = []
    for doc in code_docs:
        names.extend(doc.get("classes", []))
        names.extend(doc.get("functions", []))
    return tokenize_text(readme or "") + tokenize_identifiers(names)
