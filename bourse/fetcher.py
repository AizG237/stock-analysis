"""
Collecte des historiques OHLCV depuis Yahoo Finance.

Strategie de telechargement
---------------------------
1. **Par lots** : `yfinance.download()` accepte plusieurs symboles par appel.
   Un lot de 20 symboles = 1 aller-retour reseau au lieu de 20, ce qui divise
   d'autant le risque de se faire limiter (HTTP 429).
2. **Repli individuel** : les symboles revenus vides dans un lot (suspension,
   changement de code, valeur retiree de la cote) sont retentes un par un via
   `Ticker.history()`, qui remonte des messages d'erreur exploitables.
3. **Backoff exponentiel** : chaque etape est retentee `BOURSE_RETRY_ATTEMPTS`
   fois avec une attente croissante.

Aucune cle d'API n'est necessaire : Yahoo Finance est interroge en anonyme.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

import pandas as pd
import yfinance as yf

from bourse.config import Settings, get_settings
from bourse.universe import Asset

logger = logging.getLogger(__name__)

#: Correspondance colonnes Yahoo -> schema interne (voir storage.PRICE_COLUMNS).
_COLUMN_RENAME: dict[str, str] = {
    "Date": "date",
    "Datetime": "date",
    "index": "date",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Adj_Close": "adj_close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "stock_splits",
}

#: Nombre de symboles par appel reseau. Au-dela, Yahoo tronque les reponses.
BATCH_SIZE = 20


class FetchError(RuntimeError):
    """Le telechargement d'un symbole a echoue apres toutes les tentatives."""


@dataclass(slots=True)
class FetchResult:
    """Issue de la collecte pour un symbole."""

    asset: Asset
    frame: pd.DataFrame | None = None
    error: str | None = None
    attempts: int = 0

    @property
    def ok(self) -> bool:
        return self.frame is not None and not self.frame.empty

    @property
    def rows(self) -> int:
        return 0 if self.frame is None else len(self.frame)


@dataclass(slots=True)
class FetchReport:
    """Bilan agrege d'une campagne de collecte."""

    results: list[FetchResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[FetchResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[FetchResult]:
        return [r for r in self.results if not r.ok]

    @property
    def total_rows(self) -> int:
        return sum(r.rows for r in self.results)


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _tidy(raw: pd.DataFrame) -> pd.DataFrame:
    """Aplatit l'index et renomme les colonnes Yahoo vers le schema interne."""
    frame = raw.reset_index()
    frame = frame.rename(columns={c: _COLUMN_RENAME.get(str(c), str(c)) for c in frame.columns})

    # Yahoo ajoute parfois "Capital Gains" (fonds) : hors schema, on l'ecarte.
    known = set(_COLUMN_RENAME.values())
    frame = frame[[c for c in frame.columns if c in known]]

    # Un symbole peut renvoyer deux colonnes "close" identiques selon la
    # combinaison auto_adjust / actions : on ne garde que la premiere.
    return frame.loc[:, ~frame.columns.duplicated()]


def _extract(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Isole les colonnes d'un symbole dans le resultat d'un telechargement groupe."""
    if raw is None or raw.empty:
        return None

    frame = raw
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(raw.columns.get_level_values(0))
        level1 = set(raw.columns.get_level_values(1))
        if ticker in level0:
            frame = raw[ticker]
        elif ticker in level1:
            frame = raw.xs(ticker, axis=1, level=1)
        else:
            return None

    frame = frame.dropna(how="all")
    if frame.empty:
        return None
    return _tidy(frame)


def _with_retry(operation: Callable[[], pd.DataFrame | None], label: str, settings: Settings):
    """Execute `operation` avec backoff exponentiel. Retourne (resultat, tentatives)."""
    last_error: Exception | None = None

    for attempt in range(1, settings.retry_attempts + 1):
        try:
            outcome = operation()
            if outcome is not None and not outcome.empty:
                return outcome, attempt
            last_error = FetchError("reponse vide")
        except Exception as exc:
            last_error = exc
            logger.debug("%s : tentative %d/%d echouee (%s)",
                         label, attempt, settings.retry_attempts, exc)

        if attempt < settings.retry_attempts:
            pause = settings.retry_backoff ** attempt
            logger.debug("%s : nouvelle tentative dans %.1f s", label, pause)
            time.sleep(pause)

    if last_error is not None:
        logger.debug("%s : abandon apres %d tentatives", label, settings.retry_attempts)
    return None, settings.retry_attempts


def download_one(
    ticker: str,
    *,
    period: str | None = None,
    interval: str | None = None,
    settings: Settings | None = None,
) -> pd.DataFrame:
    """Telecharge l'historique d'un seul symbole.

    Args:
        ticker: symbole Yahoo (``"AAPL"``, ``"MC.PA"``, ``"^GSPC"``).
        period: profondeur d'historique ; par defaut celle du `.env`.
        interval: granularite ; par defaut celle du `.env`.

    Returns:
        DataFrame aux colonnes date/open/high/low/close/adj_close/volume...

    Raises:
        FetchError: aucune donnee apres epuisement des tentatives.
    """
    cfg = settings or get_settings()

    def _call() -> pd.DataFrame | None:
        history = yf.Ticker(ticker).history(
            period=period or cfg.period,
            interval=interval or cfg.interval,
            auto_adjust=False,
            actions=True,
            raise_errors=False,
        )
        return None if history is None or history.empty else _tidy(history)

    frame, _ = _with_retry(_call, ticker, cfg)
    if frame is None:
        raise FetchError(f"{ticker} : aucune donnee retournee par Yahoo Finance.")
    return frame


def download_batch(
    tickers: Sequence[str],
    *,
    period: str | None = None,
    interval: str | None = None,
    settings: Settings | None = None,
) -> dict[str, pd.DataFrame]:
    """Telecharge plusieurs symboles en un appel. Les absents sont simplement omis."""
    cfg = settings or get_settings()
    if not tickers:
        return {}

    def _call() -> pd.DataFrame | None:
        return yf.download(
            list(tickers),
            period=period or cfg.period,
            interval=interval or cfg.interval,
            auto_adjust=False,
            actions=True,
            group_by="ticker",
            threads=cfg.max_workers,
            progress=False,
        )

    raw, _ = _with_retry(_call, f"lot de {len(tickers)}", cfg)
    if raw is None:
        return {}

    extracted: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        frame = _extract(raw, ticker)
        if frame is not None:
            extracted[ticker] = frame
    return extracted


def fetch_assets(
    assets: Sequence[Asset],
    *,
    period: str | None = None,
    interval: str | None = None,
    settings: Settings | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> FetchReport:
    """Collecte l'historique de toutes les valeurs fournies.

    Procede par lots, puis retente individuellement les symboles manquants.

    Args:
        assets: valeurs a collecter.
        on_progress: callback ``(traites, total, libelle)``, appele apres chaque
            symbole. Permet de brancher une barre de progression.

    Returns:
        Un `FetchReport` listant succes et echecs, sans jamais lever :
        un symbole retire de la cote ne doit pas interrompre la campagne.
    """
    cfg = settings or get_settings()
    report = FetchReport()
    if not assets:
        return report

    by_ticker = {asset.ticker: asset for asset in assets}
    tickers = list(by_ticker)
    total = len(tickers)
    done = 0
    collected: dict[str, pd.DataFrame] = {}

    for batch in _chunks(tickers, BATCH_SIZE):
        logger.info("Telechargement du lot %s ... (+%d)", batch[0], len(batch))
        collected.update(download_batch(batch, period=period, interval=interval, settings=cfg))
        if cfg.throttle_seconds:
            time.sleep(cfg.throttle_seconds)

    for ticker in tickers:
        asset = by_ticker[ticker]
        frame = collected.get(ticker)

        if frame is None:
            # Repli : appel unitaire, plus lent mais plus tolerant.
            logger.info("%s absent du lot, reprise en appel unitaire.", ticker)
            try:
                frame = download_one(ticker, period=period, interval=interval, settings=cfg)
            except FetchError as exc:
                report.results.append(FetchResult(asset=asset, error=str(exc)))
                done += 1
                if on_progress:
                    on_progress(done, total, asset.label)
                continue
            finally:
                if cfg.throttle_seconds:
                    time.sleep(cfg.throttle_seconds)

        report.results.append(FetchResult(asset=asset, frame=frame))
        done += 1
        if on_progress:
            on_progress(done, total, asset.label)

    logger.info(
        "Collecte terminee : %d/%d symboles, %d cotations.",
        len(report.succeeded), total, report.total_rows,
    )
    return report
