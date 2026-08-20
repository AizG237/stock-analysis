"""Tests des indicateurs techniques."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bourse.indicators import (
    annualised_volatility,
    bollinger_bands,
    cumulative_performance,
    drawdown,
    macd,
    relative_strength_index,
    simple_moving_average,
    summarise,
    with_indicators,
)


def test_moyenne_mobile_attend_la_fenetre_complete(ohlcv):
    sma = simple_moving_average(ohlcv["close"], 20)
    assert sma.iloc[:19].isna().all()
    assert not np.isnan(sma.iloc[19])
    # La 20e valeur est bien la moyenne des 20 premieres clotures.
    assert sma.iloc[19] == pytest.approx(ohlcv["close"].iloc[:20].mean())


def test_rsi_reste_borne_entre_0_et_100(ohlcv):
    rsi = relative_strength_index(ohlcv["close"]).dropna()
    assert not rsi.empty
    assert rsi.between(0, 100).all()


def test_rsi_vaut_100_sur_une_serie_strictement_croissante():
    """Sans aucune baisse, le RSI de Wilder sature a 100."""
    serie = pd.Series(np.arange(1.0, 60.0))
    assert relative_strength_index(serie).dropna().iloc[-1] == pytest.approx(100.0)


def test_bandes_de_bollinger_encadrent_la_moyenne(ohlcv):
    bands = bollinger_bands(ohlcv["close"]).dropna()
    assert (bands["lower"] <= bands["middle"]).all()
    assert (bands["middle"] <= bands["upper"]).all()


def test_macd_est_la_difference_des_deux_ema(ohlcv):
    values = macd(ohlcv["close"]).dropna()
    assert set(values.columns) == {"macd", "signal", "histogram"}
    assert values["histogram"].equals(values["macd"] - values["signal"])


def test_performance_cumulee_demarre_a_100(ohlcv):
    base = cumulative_performance(ohlcv["close"]).dropna()
    assert base.iloc[0] == pytest.approx(100.0)


def test_drawdown_est_toujours_negatif_ou_nul(ohlcv):
    assert (drawdown(ohlcv["close"]).dropna() <= 1e-9).all()


def test_volatilite_nulle_sur_un_cours_constant():
    assert annualised_volatility(pd.Series([50.0] * 100)) == pytest.approx(0.0)


def test_volatilite_indefinie_si_historique_trop_court():
    assert np.isnan(annualised_volatility(pd.Series([50.0])))


def test_with_indicators_nomme_les_colonnes_de_facon_previsible(ohlcv):
    enriched = with_indicators(ohlcv, sma_windows=(20, 50), ema_windows=(12,), bollinger=20)
    for column in ("sma_20", "sma_50", "ema_12", "bb_lower", "bb_middle", "bb_upper"):
        assert column in enriched.columns
    # L'entree ne doit pas avoir ete modifiee.
    assert "sma_20" not in ohlcv.columns


def test_summarise_tolere_une_serie_vide():
    stats = summarise(pd.DataFrame(columns=["close", "high", "low", "volume"]))
    assert np.isnan(stats["last_close"])


def test_summarise_calcule_la_performance_de_periode(ohlcv):
    stats = summarise(ohlcv)
    attendu = (ohlcv["close"].iloc[-1] / ohlcv["close"].iloc[0] - 1) * 100
    assert stats["period_change_pct"] == pytest.approx(attendu)
    assert stats["highest"] == pytest.approx(ohlcv["high"].max())
