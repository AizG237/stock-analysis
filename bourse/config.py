"""
Configuration applicative.

Toutes les options se declarent dans le fichier `.env` a la racine du projet
(voir `.env.example`). Sur Streamlit Cloud, elles se declarent dans
"App settings > Secrets" : Streamlit expose les secrets de premier niveau
comme variables d'environnement, ce module fonctionne donc a l'identique.

Usage
-----
>>> from bourse.config import get_settings
>>> settings = get_settings()
>>> settings.period
'2y'
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Racine du depot : <racine>/bourse/config.py -> <racine>
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Profondeurs d'historique acceptees par l'API Yahoo Finance.
VALID_PERIODS = ("1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max")

#: Granularites acceptees. Volontairement limitees aux pas >= 1 jour :
#: l'intraday n'est disponible que sur 60 jours glissants chez Yahoo, ce qui
#: n'a pas de sens pour un historique versionne dans le depot.
VALID_INTERVALS = ("1d", "5d", "1wk", "1mo", "3mo")

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s"


class ConfigError(RuntimeError):
    """Configuration invalide : valeur absente, mal typee ou hors domaine."""


def _load_dotenv_once() -> None:
    """Charge `.env` sans jamais ecraser une variable deja presente.

    L'ordre de priorite est donc : environnement reel > .env > valeur par defaut.
    C'est ce qui permet de surcharger ponctuellement une option en ligne de
    commande (``BOURSE_PERIOD=5y python -m scripts.update_data``).
    """
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key)
    return default if value is None or not value.strip() else value.strip()


def _env_int(key: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = _env_str(key, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} doit etre un entier, recu : {raw!r}") from exc
    if value < minimum or (maximum is not None and value > maximum):
        borne = f"[{minimum}, {maximum}]" if maximum is not None else f">= {minimum}"
        raise ConfigError(f"{key} doit etre dans {borne}, recu : {value}")
    return value


def _env_float(key: str, default: float, *, minimum: float = 0.0) -> float:
    raw = _env_str(key, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} doit etre un nombre, recu : {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} doit etre >= {minimum}, recu : {value}")
    return value


def _env_list(key: str, default: str) -> tuple[str, ...]:
    raw = _env_str(key, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    """Instantane immuable de la configuration."""

    # Collecte
    period: str
    interval: str

    # Stockage
    data_dir: Path

    # Reseau
    max_workers: int
    throttle_seconds: float
    retry_attempts: int
    retry_backoff: float

    # Divers
    log_level: str
    app_title: str
    default_tickers: tuple[str, ...]
    default_chart: str

    # -- Chemins derives ---------------------------------------------------

    @property
    def raw_dir(self) -> Path:
        """Repertoire des CSV OHLCV, un fichier par valeur."""
        return self.data_dir / "raw"

    @property
    def metadata_path(self) -> Path:
        """Catalogue CSV decrivant chaque serie disponible."""
        return self.data_dir / "metadata.csv"

    @property
    def universe_path(self) -> Path:
        """Definition de l'univers de valeurs a suivre."""
        return PROJECT_ROOT / "config" / "universe.json"

    def ensure_directories(self) -> None:
        """Cree l'arborescence de donnees si elle n'existe pas encore."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retourne la configuration, chargee une seule fois par processus."""
    _load_dotenv_once()

    period = _env_str("BOURSE_PERIOD", "2y")
    if period not in VALID_PERIODS:
        raise ConfigError(
            f"BOURSE_PERIOD={period!r} invalide. Valeurs acceptees : {', '.join(VALID_PERIODS)}"
        )

    interval = _env_str("BOURSE_INTERVAL", "1d")
    if interval not in VALID_INTERVALS:
        raise ConfigError(
            f"BOURSE_INTERVAL={interval!r} invalide. "
            f"Valeurs acceptees : {', '.join(VALID_INTERVALS)}"
        )

    raw_data_dir = Path(_env_str("BOURSE_DATA_DIR", "data"))
    data_dir = raw_data_dir if raw_data_dir.is_absolute() else PROJECT_ROOT / raw_data_dir

    log_level = _env_str("BOURSE_LOG_LEVEL", "INFO").upper()
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigError(f"BOURSE_LOG_LEVEL={log_level!r} invalide.")

    return Settings(
        period=period,
        interval=interval,
        data_dir=data_dir,
        max_workers=_env_int("BOURSE_MAX_WORKERS", 4, minimum=1, maximum=16),
        throttle_seconds=_env_float("BOURSE_THROTTLE_SECONDS", 0.4),
        retry_attempts=_env_int("BOURSE_RETRY_ATTEMPTS", 3, minimum=1, maximum=10),
        retry_backoff=_env_float("BOURSE_RETRY_BACKOFF", 1.8, minimum=1.0),
        log_level=log_level,
        app_title=_env_str("APP_TITLE", "Analyse boursiere - S&P 500 / Nasdaq / CAC 40"),
        default_tickers=_env_list("APP_DEFAULT_TICKERS", "AAPL,MSFT,MC.PA"),
        default_chart=_env_str("APP_DEFAULT_CHART", "Chandeliers japonais"),
    )


def configure_logging(level: str | None = None) -> None:
    """Initialise le logger racine. Idempotent : reappelable sans effet de bord."""
    resolved = (level or get_settings().log_level).upper()
    logging.basicConfig(level=resolved, format=LOG_FORMAT, datefmt="%H:%M:%S")
    # yfinance est tres bavard en DEBUG et noie les messages utiles.
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)
