"""Tests de l'univers de valeurs."""

from __future__ import annotations

import pytest

from bourse.universe import UniverseError, load_universe, slugify_ticker


@pytest.mark.parametrize(
    ("ticker", "expected"),
    [
        ("AAPL", "AAPL"),
        ("AIR.PA", "AIR_PA"),
        ("^GSPC", "IDX_GSPC"),
        ("BRK-B", "BRK-B"),
        ("mc.pa", "MC_PA"),
        ("MT.AS", "MT_AS"),
    ],
)
def test_slugify_produit_un_nom_de_fichier_portable(ticker, expected):
    assert slugify_ticker(ticker) == expected


def test_slugs_uniques_sur_tout_l_univers():
    """Deux valeurs ne doivent jamais viser le meme CSV."""
    universe = load_universe()
    slugs = [asset.slug for asset in universe]
    assert len(slugs) == len(set(slugs))


def test_univers_charge_les_trois_indices():
    universe = load_universe()
    assert set(universe.index_names) == {"S&P 500", "Nasdaq 100", "CAC 40"}
    assert len(universe) > 100


def test_filtre_par_indice_ne_retient_que_les_membres():
    universe = load_universe()
    cac = universe.filter(indices=["CAC 40"], kinds=["stock"])
    assert cac
    assert all("CAC 40" in asset.indices for asset in cac)
    assert all(asset.currency == "EUR" for asset in cac)


def test_filtres_combines_sont_cumulatifs():
    universe = load_universe()
    selection = universe.filter(indices=["S&P 500"], sectors=["Sante"], kinds=["stock"])
    assert selection
    for asset in selection:
        assert "S&P 500" in asset.indices
        assert asset.sector == "Sante"


def test_require_leve_sur_symbole_inconnu():
    universe = load_universe()
    assert universe.get("AAPL") is not None
    with pytest.raises(UniverseError, match="inconnu"):
        universe.require("SYMBOLE_INEXISTANT")


def test_benchmarks_exclus_sur_demande():
    avec = load_universe(include_benchmarks=True)
    sans = load_universe(include_benchmarks=False)
    assert len(avec) > len(sans)
    assert not any(asset.is_index for asset in sans)
