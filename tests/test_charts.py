"""Tests des figures Plotly : structure, pas apparence."""

from __future__ import annotations

import pytest

from bourse.charts import (
    CHART_TYPES,
    DARK,
    LIGHT,
    build_comparison_figure,
    build_price_figure,
    series_color,
)
from bourse.indicators import with_indicators


@pytest.mark.parametrize("chart_type", CHART_TYPES)
def test_chaque_type_de_graphique_produit_une_figure(ohlcv, chart_type):
    figure = build_price_figure(ohlcv, label="Test (TST)", chart_type=chart_type)
    assert figure.data


def test_le_chandelier_recoit_les_quatre_series_ohlc(ohlcv):
    figure = build_price_figure(ohlcv, label="Test (TST)", chart_type="Chandeliers japonais")
    candle = figure.data[0]
    assert candle.type == "candlestick"
    for champ in ("open", "high", "low", "close"):
        assert len(getattr(candle, champ)) == len(ohlcv)


def test_bougies_creuses_vident_le_corps_haussier(ohlcv):
    figure = build_price_figure(
        ohlcv, label="Test (TST)", chart_type="Chandeliers japonais", hollow_candles=True
    )
    assert figure.data[0].increasing.fillcolor == "rgba(0,0,0,0)"


def test_chaque_panneau_ajoute_une_zone_sous_les_prix(ohlcv):
    sans = build_price_figure(ohlcv, label="T", panels=())
    avec = build_price_figure(ohlcv, label="T", panels=("Volume", "RSI (14)", "MACD"))
    assert len(avec.layout.annotations or ()) >= len(sans.layout.annotations or ())
    assert "yaxis4" in avec.layout


def test_les_overlays_apparaissent_comme_traces_nommees(ohlcv):
    enriched = with_indicators(ohlcv, sma_windows=(20, 50))
    figure = build_price_figure(
        enriched, label="T", overlays=("sma_20", "sma_50"), panels=()
    )
    noms = {trace.name for trace in figure.data}
    assert {"SMA 20", "SMA 50"} <= noms


def test_echelle_logarithmique_appliquee_au_panneau_de_prix(ohlcv):
    figure = build_price_figure(ohlcv, label="T", log_scale=True, panels=())
    assert figure.layout.yaxis.type == "log"


def test_comparaison_ramene_chaque_serie_a_100(ohlcv):
    figure = build_comparison_figure({"A": ohlcv, "B": ohlcv})
    assert len(figure.data) == 2
    for trace in figure.data:
        assert float(trace.y[0]) == pytest.approx(100.0)


def test_jamais_de_second_axe_y_superpose(ohlcv):
    """Regle de conception : chaque mesure a son propre panneau, jamais un axe jumeau."""
    figure = build_price_figure(ohlcv, label="T", panels=("Volume", "MACD"))
    for name in figure.layout:
        if name.startswith("yaxis"):
            assert getattr(figure.layout, name).overlaying is None


def test_les_couleurs_de_serie_sont_stables_par_rang():
    """La couleur suit le rang d'affectation, jamais le nombre de series affichees."""
    assert series_color(LIGHT, 0) == LIGHT.series[0]
    assert series_color(LIGHT, 8) == LIGHT.series[0]
    assert len(LIGHT.series) == len(DARK.series) == 8
