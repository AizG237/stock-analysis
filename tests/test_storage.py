"""Tests de la couche de persistance CSV."""

from __future__ import annotations

import pandas as pd
import pytest

from bourse.storage import (
    PRICE_COLUMNS,
    StorageError,
    drop_current_session,
    load_prices,
    normalise_prices,
    price_path,
    save_prices,
)


def test_aller_retour_csv_conserve_les_valeurs(isolated_settings, ohlcv):
    save_prices(ohlcv, "AIR.PA")
    assert price_path("AIR.PA").name == "AIR_PA.csv"

    relu = load_prices("AIR.PA")
    assert list(relu.columns) == list(PRICE_COLUMNS)
    assert len(relu) == len(ohlcv)
    pd.testing.assert_series_equal(
        relu["close"], ohlcv["close"], check_exact=False, rtol=1e-6
    )


def test_normalisation_trie_et_deduplique(ohlcv):
    melange = pd.concat([ohlcv.iloc[::-1], ohlcv.iloc[:5]], ignore_index=True)
    result = normalise_prices(melange)

    assert result["date"].is_monotonic_increasing
    assert not result["date"].duplicated().any()
    assert len(result) == len(ohlcv)


def test_normalisation_cree_les_colonnes_optionnelles(ohlcv):
    minimal = ohlcv[["date", "open", "high", "low", "close", "volume"]]
    result = normalise_prices(minimal)

    assert list(result.columns) == list(PRICE_COLUMNS)
    assert (result["adj_close"] == result["close"]).all()
    assert (result["dividends"] == 0.0).all()


def test_normalisation_ecarte_les_seances_sans_cotation(ohlcv):
    troue = ohlcv.copy()
    troue.loc[3, ["open", "high", "low", "close"]] = None
    assert len(normalise_prices(troue)) == len(ohlcv) - 1


def test_normalisation_refuse_un_schema_incomplet(ohlcv):
    with pytest.raises(StorageError, match="obligatoires"):
        normalise_prices(ohlcv.drop(columns=["high"]))


def test_normalisation_refuse_une_serie_vide():
    with pytest.raises(StorageError, match="vide"):
        normalise_prices(pd.DataFrame())


def test_volume_ecrit_en_entier(isolated_settings, ohlcv):
    save_prices(ohlcv, "AAPL")
    assert load_prices("AAPL")["volume"].dtype.kind == "i"


def test_drop_current_session_retire_la_bougie_du_jour(ohlcv):
    partielle = pd.concat(
        [ohlcv, ohlcv.tail(1).assign(date=pd.Timestamp.now().normalize())],
        ignore_index=True,
    )
    result = drop_current_session(partielle)

    assert len(result) == len(ohlcv)
    assert result["date"].max() < pd.Timestamp.now().normalize()


def test_lecture_d_une_serie_absente_est_explicite(isolated_settings):
    with pytest.raises(StorageError, match="update_data"):
        load_prices("SYMBOLE_ABSENT")


def test_ecriture_atomique_ne_laisse_pas_de_fichier_temporaire(isolated_settings, ohlcv):
    save_prices(ohlcv, "MSFT")
    assert not list(isolated_settings.raw_dir.glob("*.tmp"))
