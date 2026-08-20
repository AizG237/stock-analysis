"""Fixtures partagees : isolent les tests du .env et du dossier data/ reel."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bourse.config import get_settings


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Redirige le stockage vers un dossier temporaire, config figee.

    `get_settings` est memoisee : le cache doit etre vide avant ET apres, sinon
    un test contamine le suivant (ou l'application reelle).
    """
    monkeypatch.setenv("BOURSE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOURSE_PERIOD", "1y")
    monkeypatch.setenv("BOURSE_INTERVAL", "1d")
    get_settings.cache_clear()

    settings = get_settings()
    settings.ensure_directories()
    yield settings

    get_settings.cache_clear()


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    """Serie OHLCV synthetique de 120 seances ouvrees, deterministe."""
    generator = np.random.default_rng(seed=20260820)
    dates = pd.bdate_range("2025-01-01", periods=120)

    close = 100 + np.cumsum(generator.normal(0, 1.4, size=len(dates)))
    spread = np.abs(generator.normal(0, 0.9, size=len(dates)))

    return pd.DataFrame(
        {
            "date": dates,
            "open": close + generator.normal(0, 0.5, size=len(dates)),
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "adj_close": close,
            "volume": generator.integers(1_000_000, 9_000_000, size=len(dates)),
            "dividends": 0.0,
            "stock_splits": 0.0,
        }
    )
