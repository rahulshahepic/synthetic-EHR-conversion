"""Enforce package boundaries described in docs/ARCHITECTURE.md."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = {
    "src/bridge": {"testbed", "nimbus"},
    "src/nimbus": {"bridge", "testbed"},
    "testbed/halcyon": {"bridge", "nimbus"},
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_package_boundaries():
    violations = []
    for pkg, banned in FORBIDDEN.items():
        for f in (ROOT / pkg).rglob("*.py"):
            bad = _imports(f) & banned
            if bad:
                violations.append(f"{f.relative_to(ROOT)} imports {sorted(bad)}")
    assert not violations, "\n".join(violations)


def test_bridge_never_reads_answer_key():
    offenders = [
        str(f.relative_to(ROOT))
        for f in (ROOT / "src/bridge").rglob("*.py")
        if "answer_key" in f.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders
