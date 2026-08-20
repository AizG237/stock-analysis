"""
Indicateurs techniques.

Toutes les fonctions sont pures : elles prennent une `Series` (ou un
`DataFrame` OHLCV) et retournent un nouvel objet, sans jamais modifier
l'entree. Elles sont donc utilisables telles quelles dans un cache Streamlit.

Conventions
-----------
- les periodes sont exprimees en nombre de bougies (252 bougies ~ 1 an en
  journalier sur les marches actions) ;
- les premieres valeurs sont `NaN` tant que la fenetre n'est pas remplie, ce
  qui est le comportement attendu par Plotly (rien n'est trace).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Nombre de seances de bourse dans une annee civile (convention de place).
TRADING_DAYS_PER_YEAR = 252


def simple_moving_average(series: pd.Series, window: int) -> pd.Series:
    """Moyenne mobile simple sur `window` bougies."""
    return series.rolling(window=window, min_periods=window).mean()


def exponential_moving_average(series: pd.Series, window: int) -> pd.Series:
    """Moyenne mobile exponentielle (poids decroissants vers le passe)."""
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def relative_strength_index(series: pd.Series, window: int = 14) -> pd.Series:
    """RSI de Wilder, borne entre 0 et 100.

    Au-dessus de 70 la valeur est consideree surachetee, sous 30 survendue.
    Le lissage utilise la moyenne exponentielle de Wilder (alpha = 1/window),
    et non une moyenne simple, conformement a la definition d'origine.
    """
    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)

    avg_gain = gains.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = losses.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()

    # Division protegee : une serie sans aucune baisse donne un RSI de 100.
    relative_strength = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + relative_strength))
    return rsi.where(avg_loss != 0.0, 100.0).where(avg_gain.notna())


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD : difference de deux moyennes exponentielles, et sa ligne de signal.

    Returns:
        DataFrame a trois colonnes : `macd`, `signal`, `histogram`.
    """
    ema_fast = series.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = series.ewm(span=slow, adjust=False, min_periods=slow).mean()
    line = ema_fast - ema_slow
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame(
        {"macd": line, "signal": signal_line, "histogram": line - signal_line}
    )


def bollinger_bands(
    series: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Bandes de Bollinger : moyenne mobile encadree par N ecarts-types.

    Returns:
        DataFrame a trois colonnes : `lower`, `middle`, `upper`.
    """
    middle = series.rolling(window=window, min_periods=window).mean()
    deviation = series.rolling(window=window, min_periods=window).std(ddof=0)
    return pd.DataFrame(
        {
            "lower": middle - num_std * deviation,
            "middle": middle,
            "upper": middle + num_std * deviation,
        }
    )


def average_true_range(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    """ATR : amplitude moyenne des bougies, mesure d'agitation du marche.

    Prend en compte les gaps d'ouverture, contrairement a un simple high - low.
    """
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def returns(series: pd.Series) -> pd.Series:
    """Rendements simples d'une bougie a l'autre (0.012 = +1,2 %)."""
    return series.pct_change()


def cumulative_performance(series: pd.Series) -> pd.Series:
    """Performance cumulee en base 100 depuis la premiere bougie disponible."""
    valid = series.dropna()
    if valid.empty:
        return pd.Series(dtype="float64", index=series.index)
    return series / valid.iloc[0] * 100.0


def drawdown(series: pd.Series) -> pd.Series:
    """Ecart au plus haut historique, en pourcentage (valeur <= 0)."""
    running_max = series.cummax()
    return (series / running_max - 1.0) * 100.0


def annualised_volatility(
    series: pd.Series,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    """Volatilite annualisee, en pourcentage.

    Ecart-type des rendements quotidiens, remis a l'echelle annuelle par la
    racine du nombre de seances (hypothese classique de marche brownien).
    """
    daily = returns(series).dropna()
    if len(daily) < 2:
        return float("nan")
    return float(daily.std(ddof=1) * np.sqrt(periods_per_year) * 100.0)


def with_indicators(
    frame: pd.DataFrame,
    *,
    sma_windows: tuple[int, ...] = (),
    ema_windows: tuple[int, ...] = (),
    bollinger: int | None = None,
    bollinger_std: float = 2.0,
    price_column: str = "close",
) -> pd.DataFrame:
    """Retourne une copie du DataFrame enrichie des indicateurs demandes.

    Les colonnes ajoutees sont nommees de facon previsible pour que la couche
    graphique puisse les retrouver : `sma_20`, `ema_50`, `bb_upper`...

    >>> enriched = with_indicators(prices, sma_windows=(20, 50))
    >>> "sma_20" in enriched.columns
    True
    """
    result = frame.copy()
    price = result[price_column]

    for window in sma_windows:
        result[f"sma_{window}"] = simple_moving_average(price, window)

    for window in ema_windows:
        result[f"ema_{window}"] = exponential_moving_average(price, window)

    if bollinger:
        bands = bollinger_bands(price, window=bollinger, num_std=bollinger_std)
        result["bb_lower"] = bands["lower"]
        result["bb_middle"] = bands["middle"]
        result["bb_upper"] = bands["upper"]

    return result


def summarise(frame: pd.DataFrame, price_column: str = "close") -> dict[str, float]:
    """Calcule les indicateurs cles affiches en tete d'application.

    Returns:
        Dictionnaire des metriques ; les valeurs indisponibles (historique trop
        court) valent `nan` plutot que de lever une exception.
    """
    empty = {
        "last_close": float("nan"),
        "change_abs": float("nan"),
        "change_pct": float("nan"),
        "period_change_pct": float("nan"),
        "highest": float("nan"),
        "lowest": float("nan"),
        "average_volume": float("nan"),
        "volatility": float("nan"),
        "max_drawdown": float("nan"),
    }
    if frame is None or frame.empty:
        return empty

    price = frame[price_column].dropna()
    if price.empty:
        return empty

    last = float(price.iloc[-1])
    previous = float(price.iloc[-2]) if len(price) > 1 else float("nan")
    first = float(price.iloc[0])

    return {
        "last_close": last,
        "change_abs": last - previous,
        "change_pct": (last / previous - 1.0) * 100.0 if previous else float("nan"),
        "period_change_pct": (last / first - 1.0) * 100.0 if first else float("nan"),
        "highest": float(frame["high"].max()) if "high" in frame else float(price.max()),
        "lowest": float(frame["low"].min()) if "low" in frame else float(price.min()),
        "average_volume": float(frame["volume"].mean()) if "volume" in frame else float("nan"),
        "volatility": annualised_volatility(price),
        "max_drawdown": float(drawdown(price).min()),
    }
