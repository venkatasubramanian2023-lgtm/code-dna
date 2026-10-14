"""Step 3: tokenisation of identifiers and documentation text for the semantic feature."""
import re

_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]+")

STOPWORDS = frozenset("""
a about above after again all also an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has
have having he her here hers him his how i if in into is it its just me more most my no nor not
now of off on once only or other our out over own same she should so some such than that the
their them then there these they this those through to too under until up use used using very
was we were what when where which while who why will with would you your
""".split())


def split_identifier(name: str) -> list:
    """snake_case and CamelCase identifiers to lower-case words: 'parseHTTPResponse' ->
    ['parse', 'http', 'response']. Single letters are dropped."""
    parts = []
    for chunk in name.split("_"):
        parts.extend(w.lower() for w in _CAMEL.findall(chunk))
    return [p for p in parts if len(p) > 1]


def tokenize_text(text: str) -> list:
    """Words from README or documentation text, without stop words."""
    return [w for w in (t.lower() for t in _WORD.findall(text))
            if len(w) > 2 and w not in STOPWORDS]


def tokenize_identifiers(names) -> list:
    out = []
    for n in names:
        out.extend(w for w in split_identifier(n) if w not in STOPWORDS)
    return out
