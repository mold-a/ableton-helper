"""Guard the Python 3.7 compatibility of the Remote Script sources (Live 11 embeds 3.7)."""
import ast
import os

import pytest

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "AbletonHelper")
BUILTIN_GENERICS = {"list", "dict", "set", "tuple", "frozenset", "type"}


def _sources():
    out = []
    for root, _dirs, files in os.walk(PKG):
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(root, f))
    return sorted(out)


def _annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            yield node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


@pytest.mark.parametrize("path", _sources())
def test_py37_syntax(path):
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    # feature_version makes the parser reject walrus, positional-only params, etc.
    tree = ast.parse(src, filename=path, feature_version=(3, 7))
    match_node = getattr(ast, "Match", None)
    for node in ast.walk(tree):
        assert not isinstance(node, ast.NamedExpr), "walrus operator at %s:%s" % (path, node.lineno)
        if match_node is not None:
            assert not isinstance(node, match_node), "match statement at %s:%s" % (path, node.lineno)
        if isinstance(node, ast.JoinedStr):
            vals = node.values
            for a, b in zip(vals, vals[1:]):
                if (isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.endswith("=")
                        and isinstance(b, ast.FormattedValue) and b.conversion == 114):
                    raise AssertionError("f-string '=' specifier at %s:%s" % (path, node.lineno))
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            pass
    for ann in _annotations(tree):
        for n in ast.walk(ann):
            assert not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)), \
                "PEP 604 union in annotation at %s:%s" % (path, n.lineno)
            assert not (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                        and n.value.id in BUILTIN_GENERICS), \
                "PEP 585 generic in annotation at %s:%s" % (path, n.lineno)


@pytest.mark.parametrize("path", _sources())
def test_no_dynamic_code_and_py39_apis(path):
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    banned_attrs = {"removeprefix", "removesuffix", "create_server", "cached_property", "excepthook"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec", "compile", "__import__"), \
                "dynamic code at %s:%s" % (path, node.lineno)
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned_attrs, "3.8+/3.9+ API %s at %s:%s" % (node.attr, path, node.lineno)


def test_only_stdlib_imports():
    stdlib = {"os", "sys", "re", "json", "math", "queue", "socket", "threading", "time", "traceback"}
    for path in _sources():
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for n in names:
                # Live / _Framework / ableton are provided by Live itself (guarded imports)
                assert n in stdlib or n in ("Live", "_Framework", "ableton"), "%s imports %s" % (path, n)
