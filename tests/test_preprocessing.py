from codedna.extraction import semantic_tokens
from codedna.preprocessing import (detect_language, is_ignored, normalize_path, split_identifier,
                                   tokenize_identifiers, tokenize_text, walk_files)


def test_detect_language():
    assert detect_language("a/b/main.py") == "Python"
    assert detect_language("App.TSX") == "TypeScript"
    assert detect_language("notes.md") is None


def test_is_ignored_generated_files():
    assert is_ignored("app.min.js") and is_ignored("package-lock.json") and is_ignored("x_pb2.py")
    assert not is_ignored("app.js")


def test_normalize_path_uses_forward_slashes(tmp_path):
    p = tmp_path / "pkg" / "mod.py"
    assert normalize_path(str(p), str(tmp_path)) == "pkg/mod.py"


def test_walk_files_skips_vendored_and_generated(tmp_path):
    for name in ("src/a.py", "node_modules/x/b.js", "build/c.py", "dist/app.min.js", "yarn.lock"):
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    found = sorted(normalize_path(p, str(tmp_path)) for p in walk_files(str(tmp_path)))
    assert found == ["src/a.py"]


def test_split_identifier():
    assert split_identifier("parseHTTPResponse") == ["parse", "http", "response"]
    assert split_identifier("get_user_id") == ["get", "user", "id"]
    assert split_identifier("x") == []


def test_tokenize_text_drops_stopwords():
    assert tokenize_text("The quick HTTP client for the web") == ["quick", "http", "client", "web"]


def test_tokenize_identifiers():
    assert tokenize_identifiers(["fetchUserData", "Base"]) == ["fetch", "user", "data", "base"]


def test_semantic_tokens_combine_readme_and_code():
    docs = [{"classes": ["HttpClient"], "functions": ["send_request"]}]
    assert semantic_tokens("A web library", docs) == ["web", "library", "http", "client", "send", "request"]
