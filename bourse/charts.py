"""
Construction des figures Plotly.

Regles de conception appliquees
-------------------------------
- **Jamais de second axe Y superpose.** Le volume, le RSI et le MACD occupent
  chacun leur propre panneau sous les prix, avec un axe X partage. Superposer
  deux echelles sur un meme trace produit des correlations qui n'existent pas.
- **Comparaison en base 100.** Comparer plusieurs valeurs de prix differents se
  fait en indexant chaque serie a 100 a la premiere seance, sur un axe unique.
- **Couleurs categorielles a rang fixe.** La couleur suit la valeur, pas son
  classement : filtrer une serie ne repeint pas les autres.
- **Palette validee** pour les deficiences de vision des couleurs (protanopie,
  deuteranopie, tritanopie), en mode clair comme en mode sombre.
- **Hausse / baisse** utilise la paire de statut (vert / rouge), doublee d'un
  mode "bougies creuses" pour ne pas reposer sur la couleur seule.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

#: Types de graphique proposes dans l'interface.
CHART_TYPES: tuple[str, ...] = (
    "Chandeliers japonais",
    "Ligne",
    "Aire",
    "OHLC (barres)",
)

#: Panneaux d'analyse optionnels, affiches sous les prix.
PANELS: tuple[str, ...] = ("Volume", "RSI (14)", "MACD")


@dataclass(frozen=True, slots=True)
class Theme:
    """Jeton de couleurs d'un mode d'affichage."""

    surface: str
    paper: str
    ink: str
    ink_secondary: str
    muted: str
    grid: str
    axis: str
    up: str
    down: str
    series: tuple[str, ...]


#: Mode clair. Les trois teintes sous 3:1 de contraste (aqua, jaune, magenta)
#: sont compensees par une legende permanente et l'onglet "Donnees".
LIGHT = Theme(
    surface="#fcfcfb",
    paper="#f9f9f7",
    ink="#0b0b0b",
    ink_secondary="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    up="#0ca30c",
    down="#d03b3b",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
            "#e87ba4", "#008300", "#4a3aa7", "#e34948"),
)

#: Mode sombre : memes teintes, pas ajustes pour la surface sombre.
DARK = Theme(
    surface="#1a1a19",
    paper="#0d0d0d",
    ink="#ffffff",
    ink_secondary="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    up="#0ca30c",
    down="#d03b3b",
    series=("#3987e5", "#d95926", "#199e70", "#c98500",
            "#d55181", "#008300", "#9085e9", "#e66767"),
)

THEMES: dict[str, Theme] = {"light": LIGHT, "dark": DARK}

#: Couleur affectee a chaque moyenne mobile, par rang d'apparition.
_OVERLAY_SLOTS = (0, 1, 6, 3)


def get_theme(name: str = "light") -> Theme:
    """Retourne le jeu de couleurs demande, mode clair par defaut."""
    return THEMES.get(str(name).lower(), LIGHT)


def series_color(theme: Theme, position: int) -> str:
    """Couleur categorielle du rang donne.

    Au-dela de huit series la palette n'est pas recyclee : l'appelant doit
    plafonner le nombre de series (voir `MAX_COMPARISON_SERIES`).
    """
    return theme.series[position % len(theme.series)]


#: Au-dela, les couleurs ne sont plus distinguables : l'interface bloque.
MAX_COMPARISON_SERIES = len(LIGHT.series)


#: Formats d'axe temporel selon le niveau de zoom. Plotly.js n'embarque pas la
#: locale francaise : `%b` afficherait "Mar" au lieu de "mars". On s'en tient
#: donc a des formats numeriques, dans l'ordre francais jour/mois/annee.
_TICK_FORMAT_STOPS = (
    {"dtickrange": [None, 604_800_000], "value": "%d/%m"},              # < 1 semaine
    {"dtickrange": [604_800_000, 2_592_000_000], "value": "%d/%m"},     # < 1 mois
    {"dtickrange": [2_592_000_000, 31_536_000_000], "value": "%m/%Y"},  # < 1 an
    {"dtickrange": [31_536_000_000, None], "value": "%Y"},
)


def _time_rangebreaks(dates: pd.Series, *, skip_weekends: bool) -> list[dict]:
    """Coupures d'axe a appliquer pour supprimer les seances non cotees.

    Masquer les seuls week-ends ne suffit pas : chaque jour ferie de place
    (Vendredi saint, 1er mai, Thanksgiving...) laisse un trou dans les
    chandeliers. On deduit ces jours de l'ecart entre le calendrier ouvre
    theorique et les dates reellement presentes dans la serie.
    """
    if not skip_weekends or dates.empty:
        return []

    breaks: list[dict] = [{"bounds": ["sat", "mon"]}]

    business_days = pd.bdate_range(dates.min(), dates.max())
    holidays = business_days.difference(pd.DatetimeIndex(dates.dt.normalize()))
    if len(holidays):
        breaks.append({"values": [d.strftime("%Y-%m-%d") for d in holidays]})
    return breaks


def _axis_style(theme: Theme, *, grid: bool = True) -> dict:
    """Style commun des axes : discret, sans trait en pointilles."""
    return {
        "showgrid": grid,
        "gridcolor": theme.grid,
        "gridwidth": 1,
        "zeroline": False,
        "linecolor": theme.axis,
        "tickfont": {"color": theme.muted, "size": 11},
        "title_font": {"color": theme.ink_secondary, "size": 12},
    }


def _range_selector(theme: Theme) -> dict:
    """Boutons de plage temporelle, poses au-dessus du graphique."""
    return {
        "buttons": [
            {"count": 1, "label": "1M", "step": "month", "stepmode": "backward"},
            {"count": 3, "label": "3M", "step": "month", "stepmode": "backward"},
            {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
            {"count": 1, "label": "1A", "step": "year", "stepmode": "backward"},
            {"step": "all", "label": "Tout"},
        ],
        "bgcolor": theme.surface,
        "activecolor": theme.grid,
        "bordercolor": theme.axis,
        "borderwidth": 1,
        "font": {"color": theme.ink_secondary, "size": 11},
        "x": 0,
        "y": 1.0,
        "yanchor": "bottom",
    }


def _hover_number(currency: str) -> str:
    return f",.2f {currency}" if currency else ",.2f"


def _price_trace(
    frame: pd.DataFrame,
    chart_type: str,
    theme: Theme,
    label: str,
    currency: str,
    hollow: bool,
) -> list[go.BaseTraceType]:
    """Construit la ou les traces du panneau de prix selon le type demande."""
    dates = frame["date"]

    if chart_type == "Chandeliers japonais":
        return [
            go.Candlestick(
                x=dates,
                open=frame["open"], high=frame["high"],
                low=frame["low"], close=frame["close"],
                name=label,
                increasing_line_color=theme.up,
                decreasing_line_color=theme.down,
                # Bougies creuses : la hausse devient un contour vide. La
                # direction cesse alors de reposer sur la seule couleur.
                increasing_fillcolor="rgba(0,0,0,0)" if hollow else theme.up,
                decreasing_fillcolor=theme.down,
                line_width=1,
                whiskerwidth=0,
                showlegend=False,
            )
        ]

    if chart_type == "OHLC (barres)":
        return [
            go.Ohlc(
                x=dates,
                open=frame["open"], high=frame["high"],
                low=frame["low"], close=frame["close"],
                name=label,
                increasing_line_color=theme.up,
                decreasing_line_color=theme.down,
                line_width=1,
                showlegend=False,
            )
        ]

    fill = "tozeroy" if chart_type == "Aire" else None
    colour = series_color(theme, 0)
    return [
        go.Scatter(
            x=dates,
            y=frame["close"],
            name=f"{label} - cloture",
            mode="lines",
            line={"color": colour, "width": 2},
            fill=fill,
            fillcolor="rgba(42,120,214,0.12)" if fill else None,
            hovertemplate="Cloture %{y:" + _hover_number(currency) + "}<extra></extra>",
            showlegend=False,
        )
    ]


def _overlay_traces(
    frame: pd.DataFrame, theme: Theme, overlays: tuple[str, ...]
) -> list[go.Scatter]:
    """Moyennes mobiles et bandes de Bollinger posees sur le panneau de prix."""
    traces: list[go.Scatter] = []
    rank = 0

    for column in overlays:
        if column not in frame.columns or column.startswith("bb_"):
            continue
        kind, _, window = column.partition("_")
        traces.append(
            go.Scatter(
                x=frame["date"], y=frame[column],
                name=f"{kind.upper()} {window}",
                mode="lines",
                line={"color": series_color(theme, _OVERLAY_SLOTS[rank % len(_OVERLAY_SLOTS)]),
                      "width": 2},
                hovertemplate=f"{kind.upper()} {window} " + "%{y:,.2f}<extra></extra>",
            )
        )
        rank += 1

    if {"bb_upper", "bb_lower"} <= set(overlays) & set(frame.columns):
        traces.append(
            go.Scatter(x=frame["date"], y=frame["bb_upper"], name="Bollinger haute",
                       mode="lines", line={"color": theme.muted, "width": 1},
                       hoverinfo="skip", showlegend=False)
        )
        traces.append(
            go.Scatter(x=frame["date"], y=frame["bb_lower"], name="Bandes de Bollinger",
                       mode="lines", line={"color": theme.muted, "width": 1},
                       fill="tonexty", fillcolor="rgba(137,135,129,0.12)",
                       hoverinfo="skip")
        )

    return traces


def _add_volume(figure: go.Figure, frame: pd.DataFrame, theme: Theme, row: int) -> None:
    """Volume echange, en barres fines et recessives.

    Volontairement monochrome : la direction de la seance est deja portee par
    le panneau de prix, la redoubler ici n'ajouterait que du bruit.
    """
    figure.add_trace(
        go.Bar(
            x=frame["date"], y=frame["volume"], name="Volume",
            marker={"color": theme.muted, "line_width": 0},
            opacity=0.55,
            hovertemplate="Volume %{y:,.0f}<extra></extra>",
            showlegend=False,
        ),
        row=row, col=1,
    )
    figure.update_yaxes(title_text="Volume", row=row, col=1, **_axis_style(theme))


def _add_rsi(figure: go.Figure, frame: pd.DataFrame, theme: Theme, row: int) -> None:
    """RSI 14 avec ses seuils conventionnels de surachat / survente."""
    from bourse.indicators import relative_strength_index

    figure.add_trace(
        go.Scatter(
            x=frame["date"], y=relative_strength_index(frame["close"]),
            name="RSI (14)", mode="lines",
            line={"color": series_color(theme, 6), "width": 2},
            hovertemplate="RSI %{y:.1f}<extra></extra>",
            showlegend=False,
        ),
        row=row, col=1,
    )
    for level, dash_label in ((70, "surachat"), (30, "survente")):
        figure.add_hline(
            y=level, row=row, col=1,
            line={"color": theme.axis, "width": 1},
            annotation_text=dash_label,
            annotation_font={"color": theme.muted, "size": 10},
            annotation_position="top left",
        )
    figure.update_yaxes(title_text="RSI", range=[0, 100], row=row, col=1, **_axis_style(theme))


def _add_macd(figure: go.Figure, frame: pd.DataFrame, theme: Theme, row: int) -> None:
    """MACD, sa ligne de signal et l'histogramme d'ecart."""
    from bourse.indicators import macd

    values = macd(frame["close"])
    figure.add_trace(
        go.Bar(
            x=frame["date"], y=values["histogram"], name="Ecart MACD",
            marker={"color": theme.muted, "line_width": 0}, opacity=0.5,
            hovertemplate="Ecart %{y:.3f}<extra></extra>", showlegend=False,
        ),
        row=row, col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=frame["date"], y=values["macd"], name="MACD", mode="lines",
            line={"color": series_color(theme, 0), "width": 2},
            hovertemplate="MACD %{y:.3f}<extra></extra>",
        ),
        row=row, col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=frame["date"], y=values["signal"], name="Signal", mode="lines",
            line={"color": series_color(theme, 1), "width": 2},
            hovertemplate="Signal %{y:.3f}<extra></extra>",
        ),
        row=row, col=1,
    )
    figure.update_yaxes(title_text="MACD", row=row, col=1, **_axis_style(theme))


_PANEL_BUILDERS = {"Volume": _add_volume, "RSI (14)": _add_rsi, "MACD": _add_macd}


def build_price_figure(
    frame: pd.DataFrame,
    *,
    label: str,
    chart_type: str = "Chandeliers japonais",
    theme_name: str = "light",
    overlays: tuple[str, ...] = (),
    panels: tuple[str, ...] = ("Volume",),
    currency: str = "",
    log_scale: bool = False,
    hollow_candles: bool = False,
    skip_weekends: bool = True,
    height: int = 720,
) -> go.Figure:
    """Assemble la figure principale : prix, puis un panneau par analyse demandee.

    Args:
        frame: serie OHLCV, deja enrichie des overlays par `indicators.with_indicators`.
        label: libelle de la valeur, utilise en titre et dans les infobulles.
        chart_type: une valeur de `CHART_TYPES`.
        overlays: colonnes d'indicateurs a superposer (`sma_20`, `bb_upper`...).
        panels: panneaux sous les prix, parmi `PANELS`, dans l'ordre voulu.
        skip_weekends: masque samedi et dimanche, sans quoi les chandeliers
            journaliers affichent un trou tous les cinq jours.

    Returns:
        Une figure Plotly prete pour `st.plotly_chart`.
    """
    theme = get_theme(theme_name)
    wanted = tuple(p for p in panels if p in _PANEL_BUILDERS)

    panel_height = 0.18
    price_height = max(0.34, 1.0 - panel_height * len(wanted))
    remaining = (1.0 - price_height) / len(wanted) if wanted else 0.0

    figure = make_subplots(
        rows=1 + len(wanted), cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[price_height] + [remaining] * len(wanted),
    )

    for trace in _price_trace(frame, chart_type, theme, label, currency, hollow_candles):
        figure.add_trace(trace, row=1, col=1)
    for trace in _overlay_traces(frame, theme, overlays):
        figure.add_trace(trace, row=1, col=1)

    for offset, panel in enumerate(wanted, start=2):
        _PANEL_BUILDERS[panel](figure, frame, theme, offset)

    axis_title = f"Cours ({currency})" if currency else "Cours"
    figure.update_yaxes(
        title_text=axis_title, row=1, col=1,
        type="log" if log_scale else "linear",
        **_axis_style(theme),
    )
    figure.update_xaxes(
        **_axis_style(theme, grid=False),
        showspikes=True, spikemode="across", spikethickness=1,
        spikecolor=theme.axis, spikedash="solid",
    )
    figure.update_xaxes(rangeslider_visible=False, tickformatstops=_TICK_FORMAT_STOPS)
    figure.update_xaxes(rangeselector=_range_selector(theme), row=1, col=1)
    figure.update_xaxes(rangebreaks=_time_rangebreaks(frame["date"], skip_weekends=skip_weekends))

    figure.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 56, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=theme.surface,
        font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif',
              "color": theme.ink_secondary, "size": 12},
        hovermode="x unified",
        hoverlabel={"bgcolor": theme.surface, "bordercolor": theme.axis,
                    "font": {"color": theme.ink, "size": 12}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0,
                "xanchor": "right", "x": 1.0,
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"color": theme.ink_secondary, "size": 11}},
        barmode="relative",
        dragmode="pan",
    )
    return figure


def build_comparison_figure(
    series: dict[str, pd.DataFrame],
    *,
    theme_name: str = "light",
    price_column: str = "close",
    height: int = 560,
    direct_label_limit: int = 4,
) -> go.Figure:
    """Compare plusieurs valeurs sur un axe unique, en base 100.

    Des cours de 12 EUR et de 900 USD ne se comparent pas sur la meme echelle.
    Chaque serie est donc ramenee a 100 a sa premiere seance commune : le
    graphique lit alors des performances relatives, pas des prix.

    Args:
        series: mapping libelle -> DataFrame contenant `date` et `price_column`.
        direct_label_limit: au-dela de ce nombre de series, on s'appuie sur la
            seule legende ; en-deca, chaque courbe est etiquetee a son extremite.
    """
    theme = get_theme(theme_name)
    figure = go.Figure()

    labelled = len(series) <= direct_label_limit

    for position, (label, frame) in enumerate(series.items()):
        values = frame[price_column].dropna()
        if values.empty:
            continue

        indexed = frame[price_column] / values.iloc[0] * 100.0
        colour = series_color(theme, position)

        figure.add_trace(
            go.Scatter(
                x=frame["date"], y=indexed, name=label, mode="lines",
                line={"color": colour, "width": 2},
                hovertemplate=f"{label} %{{y:.1f}}<extra></extra>",
            )
        )

        if labelled:
            figure.add_annotation(
                x=frame["date"].iloc[-1], y=float(indexed.dropna().iloc[-1]),
                text=f"  {label} {indexed.dropna().iloc[-1]:.0f}",
                showarrow=False, xanchor="left", yanchor="middle",
                font={"color": theme.ink_secondary, "size": 11},
            )

    figure.add_hline(y=100, line={"color": theme.axis, "width": 1})

    all_dates = pd.Series(
        sorted({d for frame in series.values() for d in frame["date"]}),
        dtype="datetime64[ns]",
    )

    figure.update_yaxes(title_text="Base 100 a la premiere seance", **_axis_style(theme))
    figure.update_xaxes(
        **_axis_style(theme, grid=False),
        showspikes=True, spikemode="across", spikethickness=1,
        spikecolor=theme.axis, spikedash="solid",
        tickformatstops=_TICK_FORMAT_STOPS,
        rangebreaks=_time_rangebreaks(all_dates, skip_weekends=True),
        rangeselector=_range_selector(theme),
    )
    figure.update_layout(
        height=height,
        margin={"l": 8, "r": 96 if labelled else 8, "t": 56, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=theme.surface,
        font={"family": 'system-ui, -apple-system, "Segoe UI", sans-serif',
              "color": theme.ink_secondary, "size": 12},
        hovermode="x unified",
        hoverlabel={"bgcolor": theme.surface, "bordercolor": theme.axis,
                    "font": {"color": theme.ink, "size": 12}},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0,
                "xanchor": "right", "x": 1.0,
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"color": theme.ink_secondary, "size": 11}},
        dragmode="pan",
    )
    return figure


def empty_figure(message: str, theme_name: str = "light", height: int = 320) -> go.Figure:
    """Figure de repli affichant un message, sans axes ni grille."""
    theme = get_theme(theme_name)
    figure = go.Figure()
    figure.add_annotation(
        text=message, showarrow=False,
        font={"color": theme.muted, "size": 13},
        xref="paper", yref="paper", x=0.5, y=0.5,
    )
    figure.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=theme.surface,
        xaxis={"visible": False}, yaxis={"visible": False},
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
    )
    return figure
