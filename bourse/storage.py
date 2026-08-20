"""
Persistance des donnees en CSV.

Choix d'architecture : un fichier CSV par valeur dans `data/raw/`, plus un
catalogue `data/metadata.csv`. Ce format a ete retenu pour l'hebergement sur
Streamlit Cloud :

- les CSV sont versionnables dans Git (lisibles, diffables, sans binaire) ;
- l'application ne charge que les series effectivement selectionnees ;
- aucune base de donnees ni service externe n'est requis a l'execution.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from bourse.config import get_settings
from bourse.universe import Asset, slugify_ticker

logger = logging.getLogger(__name__)

#: Schema complet d'un fichier de prix, dans l'ordre des colonnes.
PRICE_COLUMNS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
)

#: Colonnes sans lesquelles une serie est inexploitable (chandelier japonais).
REQUIRED_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")

#: Colonnes du catalogue `data/metadata.csv`.
METADATA_COLUMNS: tuple[str, ...] = (
    "ticker",
    "slug",
    "name",
    "sector",
    "currency",
    "indices",
    "kind",
    "rows",
    "start_date",
    "end_date",
    "last_close",
    "interval",
    "file",
    "updated_at",
)


class StorageError(RuntimeError):
    """Fichier de donnees absent, illisible ou au schema inattendu."""


# --------------------------------------------------------------------------
# Chemins
# --------------------------------------------------------------------------

def price_path(ticker: str) -> Path:
    """Chemin du CSV de prix pour un symbole donne."""
    return get_settings().raw_dir / f"{slugify_ticker(ticker)}.csv"


def has_data(ticker: str) -> bool:
    """Indique si une serie a deja ete collectee pour ce symbole."""
    return price_path(ticker).is_file()


# --------------------------------------------------------------------------
# Ecriture
# --------------------------------------------------------------------------

def _atomic_write(frame: pd.DataFrame, destination: Path) -> None:
    """Ecrit le CSV via un fichier temporaire puis un renommage atomique.

    Evite de laisser un CSV tronque derriere soi si la collecte est
    interrompue (Ctrl+C, coupure reseau, quota disque).
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    frame.to_csv(temporary, index=False, float_format="%.6f", encoding="utf-8")
    os.replace(temporary, destination)


def normalise_prices(frame: pd.DataFrame) -> pd.DataFrame:
    """Met une serie brute au schema `PRICE_COLUMNS`.

    - dates converties en `datetime64` puis triees, sans fuseau horaire
      (Yahoo renvoie des dates localisees qui rendent les CSV illisibles) ;
    - colonnes optionnelles absentes creees a zero ;
    - lignes sans cotation exploitable supprimees (jours feries, suspensions) ;
    - doublons de dates supprimes (on conserve la derniere occurrence).
    """
    if frame is None or frame.empty:
        raise StorageError("Serie vide : rien a enregistrer.")

    result = frame.copy()

    missing = [column for column in REQUIRED_COLUMNS if column not in result.columns]
    if missing:
        raise StorageError(f"Colonnes obligatoires manquantes : {missing}")

    result["date"] = pd.to_datetime(result["date"], errors="coerce", utc=True).dt.tz_localize(None)
    result = result.dropna(subset=["date"])

    if "adj_close" not in result.columns:
        result["adj_close"] = result["close"]
    for optional in ("dividends", "stock_splits"):
        if optional not in result.columns:
            result[optional] = 0.0

    numeric = [c for c in PRICE_COLUMNS if c != "date"]
    result[numeric] = result[numeric].apply(pd.to_numeric, errors="coerce")

    result = result.dropna(subset=["open", "high", "low", "close"], how="any")
    result = result.drop_duplicates(subset="date", keep="last").sort_values("date")

    result["volume"] = result["volume"].fillna(0).round().astype("int64")
    result[["dividends", "stock_splits"]] = result[["dividends", "stock_splits"]].fillna(0.0)

    if result.empty:
        raise StorageError("Serie vide apres nettoyage : aucune cotation exploitable.")

    return result[list(PRICE_COLUMNS)].reset_index(drop=True)


def drop_current_session(frame: pd.DataFrame) -> pd.DataFrame:
    """Retire la bougie du jour, susceptible d'etre incomplete.

    Une collecte lancee marche ouverte ramene une derniere bougie dont le
    cours de cloture et le volume ne sont pas definitifs. Sur un graphique en
    chandeliers, cette bougie partielle se lit exactement comme une vraie et
    induit en erreur : mieux vaut l'ecarter que la publier.
    """
    if frame is None or frame.empty or "date" not in frame.columns:
        return frame
    today = pd.Timestamp.now().normalize()
    dates = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.tz_localize(None)
    return frame.loc[dates.dt.normalize() < today].copy()


def save_prices(frame: pd.DataFrame, ticker: str) -> Path:
    """Normalise puis enregistre une serie de prix. Retourne le chemin ecrit."""
    normalised = normalise_prices(frame)
    destination = price_path(ticker)
    _atomic_write(normalised, destination)
    logger.debug("%s : %d lignes ecrites dans %s", ticker, len(normalised), destination.name)
    return destination


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------

def load_prices(ticker: str) -> pd.DataFrame:
    """Charge la serie d'un symbole depuis son CSV.

    Raises:
        StorageError: si le fichier n'existe pas (collecte jamais lancee).
    """
    source = price_path(ticker)
    if not source.is_file():
        raise StorageError(
            f"Aucune donnee pour {ticker!r} ({source.name}). "
            "Lancer d'abord : python -m scripts.update_data"
        )

    frame = pd.read_csv(source, parse_dates=["date"])
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise StorageError(f"{source.name} : colonnes manquantes {missing}")
    return frame.sort_values("date").reset_index(drop=True)


def load_many(tickers: list[str] | tuple[str, ...]) -> dict[str, pd.DataFrame]:
    """Charge plusieurs series. Les symboles sans donnees sont ignores."""
    loaded: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            loaded[ticker] = load_prices(ticker)
        except StorageError as exc:
            logger.warning("%s ignore : %s", ticker, exc)
    return loaded


# --------------------------------------------------------------------------
# Catalogue de metadonnees
# --------------------------------------------------------------------------

def build_metadata_row(asset: Asset, frame: pd.DataFrame, interval: str) -> dict:
    """Construit la ligne de catalogue decrivant une serie fraichement collectee."""
    return {
        "ticker": asset.ticker,
        "slug": asset.slug,
        "name": asset.name,
        "sector": asset.sector,
        "currency": asset.currency,
        "indices": ", ".join(asset.indices),
        "kind": asset.kind,
        "rows": len(frame),
        "start_date": frame["date"].min().date().isoformat(),
        "end_date": frame["date"].max().date().isoformat(),
        "last_close": round(float(frame["close"].iloc[-1]), 4),
        "interval": interval,
        "file": f"{asset.slug}.csv",
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def write_metadata(rows: list[dict]) -> Path:
    """Ecrit le catalogue.

    Les valeurs deja presentes mais absentes de cette collecte (par exemple si
    l'on a relance le script sur un seul indice) sont conservees telles quelles.
    """
    settings = get_settings()
    fresh = pd.DataFrame(rows, columns=list(METADATA_COLUMNS))

    if settings.metadata_path.is_file() and not fresh.empty:
        previous = pd.read_csv(settings.metadata_path)
        untouched = previous[~previous["ticker"].isin(fresh["ticker"])]
        fresh = pd.concat([untouched, fresh], ignore_index=True)

    fresh = fresh.sort_values(["kind", "ticker"], ascending=[False, True])
    settings.metadata_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(fresh, settings.metadata_path)
    return settings.metadata_path


def load_metadata() -> pd.DataFrame:
    """Charge le catalogue. Retourne un DataFrame vide si la collecte n'a pas eu lieu."""
    path = get_settings().metadata_path
    if not path.is_file():
        return pd.DataFrame(columns=list(METADATA_COLUMNS))
    return pd.read_csv(path)
