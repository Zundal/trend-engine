"""Source contract tests — every registered source must satisfy these against its fixtures.

Adding a source? Register it + drop a fixture in tests/fixtures/<name>/ and this file tests it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trend_engine.config import Settings
from trend_engine.sources import REGISTRY

FIXTURES = Settings().fixtures_dir
CASES = [
    (name, path)
    for name, src in REGISTRY.items()
    for path in sorted((FIXTURES / name).glob(f"*.{src.fixture_ext}"))
]


def test_every_source_has_a_fixture():
    covered = {name for name, _ in CASES}
    assert covered == set(REGISTRY), f"missing fixtures for {set(REGISTRY) - covered}"


@pytest.mark.parametrize("name,path", CASES, ids=[f"{n}/{p.name}" for n, p in CASES])
def test_parse_contract(name: str, path: Path):
    src = REGISTRY[name]
    region = path.stem
    items = src.parse(path.read_text(encoding="utf-8"), region)

    assert items, "parse() returned nothing — upstream format changed?"
    assert [i.rank for i in items] == list(range(1, len(items) + 1)), "ranks must be contiguous 1..n"
    for i in items:
        assert i.source == name
        assert i.region == region
        assert i.kind == src.kind
        assert i.keyword and i.keyword == i.keyword.strip()
        assert i.volume is None or i.volume >= 0
        assert isinstance(i.related, list) and isinstance(i.meta, dict)
        i.to_dict()  # must be JSON-able dataclass


@pytest.mark.parametrize("name", list(REGISTRY))
def test_parse_is_pure(name: str):
    """Same raw -> same output (no clock / network / randomness inside parse)."""
    src = REGISTRY[name]
    path = next((FIXTURES / name).glob(f"*.{src.fixture_ext}"))
    raw = path.read_text(encoding="utf-8")
    a = [i.to_dict() for i in src.parse(raw, path.stem)]
    b = [i.to_dict() for i in src.parse(raw, path.stem)]
    assert a == b


def test_source_metadata_sane():
    for s in REGISTRY.values():
        assert s.name and s.label
        assert 0 < s.weight <= 1
        assert s.kind in ("keyword", "content")
        for key in s.requires:
            assert hasattr(Settings(), key), f"{s.name}.requires references unknown setting {key}"
