from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "balcony_watering"
FORBIDDEN_AUTH_TERMS = (
    "api_key",
    "api_token",
    "authentication",
    "authorization",
    "authenticate",
    "bearer",
    "token_bearing",
    "unauthorized",
    "x_api_key",
    "x_auth_token",
)


def _normalized_ast_values(source: str) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        value: str | None = None
        if isinstance(node, ast.Name):
            value = node.id
        elif isinstance(node, ast.Attribute):
            value = node.attr
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
        if value is not None:
            values.add(re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_"))
    return values


def test_bridge_production_has_no_atom_authentication_plumbing() -> None:
    findings: list[str] = []
    for path in sorted(PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for value in _normalized_ast_values(source):
            for term in FORBIDDEN_AUTH_TERMS:
                if term in value:
                    findings.append(f"{path.name}: {term} in {value}")

    assert findings == []
