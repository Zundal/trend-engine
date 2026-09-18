"""Shared harness fixtures. Tests NEVER touch the network: Settings(offline=True) + fixtures."""

from __future__ import annotations

import pytest

from trend_engine.config import Settings
from trend_engine.service import TrendService
from trend_engine.store import Store


@pytest.fixture
def settings() -> Settings:
    return Settings(offline=True, db_path=":memory:")


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


@pytest.fixture
def service(settings, store) -> TrendService:
    return TrendService(settings, store)
