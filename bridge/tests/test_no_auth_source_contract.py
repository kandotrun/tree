from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "balcony_watering"
FORBIDDEN_AUTH_MARKERS = (
    "ATOM_API_TOKEN",
    "atom_api_token",
    "token-bearing",
    "Authorization",
    "Bearer",
)


def test_bridge_production_has_no_atom_authentication_plumbing() -> None:
    findings: list[str] = []
    for path in sorted(PACKAGE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_AUTH_MARKERS:
            if marker in source:
                findings.append(f"{path.name}: {marker}")

    assert findings == []
