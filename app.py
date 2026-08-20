"""
Application Streamlit : exploration des historiques boursiers.

Lancement local :
    streamlit run app.py

L'application ne contacte jamais Yahoo Finance : elle lit uniquement les CSV
produits par `python -m scripts.update_data`. C'est ce qui permet de l'heberger
sur Streamlit Cloud sans quota d'API ni temps de chargement au demarrage.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from bourse import __version__
from bourse.charts import (
    CHART_TYPES,
    MAX_COMPARISON_SERIES,
    PANELS,
    build_comparison_figure,
    build_price_figure,
    empty_figure,
)
from bourse.config import ConfigError, get_settings
from bourse.indicators import summarise, with_indicators
from bourse.storage import StorageError, load_metadata, load_prices
from bourse.universe import UniverseError, load_universe

COMPARISON = "Comparaison (base 100)"
ALL_CHART_TYPES = (*CHART_TYPES, COMPARISON)

#: Au-dela, la page devient lourde et illisible (une figure par valeur).
MAX_INDIVIDUAL_CHARTS = 6

#: Fenetres proposees pour les moyennes mobiles.
MA_WINDOWS = (5, 10, 20, 50, 100, 200)

PLOTLY_CONFIG = {
    "displaylogo": False,
    "scrollZoom": True,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}


# --------------------------------------------------------------------------
# Chargement (mis en cache : les CSV ne changent pas pendant une session)
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def cached_catalogue() -> pd.DataFrame:
    """Catalogue des series disponibles, lu une fois par session."""
    return load_metadata()


@st.cache_data(show_spinner=False)
def cached_series(ticker: str) -> pd.DataFrame:
    """Historique d'une valeur. Une entree de cache par symbole consulte."""
    return load_prices(ticker)


def chart_theme() -> str:
    """Mode d'affichage a appliquer aux figures.

    Streamlit n'expose la resolution du theme cote navigateur qu'a partir des
    versions recentes ; on retombe sinon sur le theme declare dans
    `.streamlit/config.toml`.
    """
    context_theme = getattr(getattr(st, "context", None), "theme", None)
    resolved = getattr(context_theme, "type", None)
    if resolved:
        return str(resolved).lower()
    return str(st.get_option("theme.base") or "light").lower()


def format_amount(value: float, currency: str) -> str:
    """Formate un montant a la francaise : espace milliers, virgule decimale."""
    if pd.isna(value):
        return "-"
    formatted = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {currency}".strip()


def format_volume(value: float) -> str:
    if pd.isna(value):
        return "-"
    for threshold, suffix in ((1e9, " Md"), (1e6, " M"), (1e3, " k")):
        if abs(value) >= threshold:
            return f"{value / threshold:,.1f}".replace(".", ",") + suffix
    return f"{value:,.0f}".replace(",", " ")


# --------------------------------------------------------------------------
# Barre laterale : perimetre et options de trace
# --------------------------------------------------------------------------

def sidebar_controls(catalogue: pd.DataFrame, universe) -> dict:
    """Dessine tous les controles et retourne la selection de l'utilisateur."""
    settings = get_settings()
    available = set(catalogue["ticker"])

    with st.sidebar:
        st.header("Perimetre")

        indices = st.multiselect(
            "Indices",
            options=list(universe.index_names),
            default=list(universe.index_names),
            help="Filtre la liste des valeurs proposees ci-dessous.",
        )
        show_benchmarks = st.toggle(
            "Inclure les indices eux-memes", value=False,
            help="Ajoute ^GSPC, ^NDX, ^FCHI... a la liste des valeurs.",
        )

        kinds = ("stock", "index") if show_benchmarks else ("stock",)
        candidates = [
            asset for asset in universe.filter(indices=indices, kinds=kinds)
            if asset.ticker in available
        ]

        sectors = st.multiselect(
            "Secteurs",
            options=sorted({asset.sector for asset in candidates}),
            default=[],
            help="Laisser vide pour ne pas filtrer par secteur.",
        )
        if sectors:
            candidates = [asset for asset in candidates if asset.sector in sectors]

        labels = {asset.label: asset for asset in candidates}
        defaults = [
            asset.label for asset in candidates
            if asset.ticker in settings.default_tickers
        ] or list(labels)[:1]

        st.divider()
        st.header("Graphique")

        chart_type = st.selectbox(
            "Type de graphique",
            options=ALL_CHART_TYPES,
            index=ALL_CHART_TYPES.index(settings.default_chart)
            if settings.default_chart in ALL_CHART_TYPES else 0,
        )
        is_comparison = chart_type == COMPARISON
        maximum = MAX_COMPARISON_SERIES if is_comparison else MAX_INDIVIDUAL_CHARTS

        chosen = st.multiselect(
            "Valeurs",
            options=list(labels),
            default=defaults[:maximum],
            max_selections=maximum,
            help=f"{maximum} valeurs au maximum pour ce type de graphique.",
        )
        selection = [labels[label] for label in chosen]

        bounds = (
            pd.to_datetime(catalogue["start_date"]).min().date(),
            pd.to_datetime(catalogue["end_date"]).max().date(),
        )
        date_range = st.date_input(
            "Periode affichee",
            value=bounds,
            min_value=bounds[0],
            max_value=bounds[1],
            help="Filtre les donnees chargees. Les boutons 1M / 3M / 6M / 1A du "
                 "graphique zooment sans recharger.",
        )

        log_scale = st.toggle(
            "Echelle logarithmique", value=False,
            help="Rend comparables des variations de meme ampleur relative.",
        )
        hollow = False
        if chart_type == "Chandeliers japonais":
            hollow = st.toggle(
                "Bougies creuses", value=False,
                help="Les seances haussieres deviennent des contours vides : "
                     "la direction ne repose plus sur la seule couleur.",
            )

        st.divider()
        st.header("Indicateurs")

        sma = st.multiselect("Moyennes mobiles simples", MA_WINDOWS, default=[20, 50],
                             disabled=is_comparison)
        ema = st.multiselect("Moyennes mobiles exponentielles", MA_WINDOWS, default=[],
                             disabled=is_comparison)
        bollinger = st.toggle("Bandes de Bollinger (20)", value=False, disabled=is_comparison)

        panels = st.multiselect(
            "Panneaux d'analyse", PANELS, default=["Volume"],
            disabled=is_comparison,
            help="Chaque panneau occupe sa propre zone sous les prix.",
        )

        st.divider()
        st.caption(f"bourse-project v{__version__} - donnees Yahoo Finance")

    return {
        "selection": selection,
        "date_range": date_range,
        "chart_type": chart_type,
        "is_comparison": is_comparison,
        "log_scale": log_scale,
        "hollow": hollow,
        "sma": tuple(sorted(sma)),
        "ema": tuple(sorted(ema)),
        "bollinger": bollinger,
        "panels": tuple(panels),
    }


# --------------------------------------------------------------------------
# Rendu principal
# --------------------------------------------------------------------------

def slice_period(frame: pd.DataFrame, date_range) -> pd.DataFrame:
    """Restreint une serie a la periode choisie.

    `st.date_input` renvoie un tuple incomplet tant que l'utilisateur n'a pas
    clique la seconde date : on ne filtre alors que sur la borne connue.
    """
    if not isinstance(date_range, tuple | list) or not date_range:
        return frame

    result = frame[frame["date"] >= pd.Timestamp(date_range[0])]
    if len(date_range) > 1:
        # Borne haute inclusive : on prend toute la journee de fin.
        result = result[result["date"] < pd.Timestamp(date_range[1]) + pd.Timedelta(days=1)]
    return result.reset_index(drop=True)


def render_kpis(frame: pd.DataFrame, currency: str) -> None:
    """Bandeau d'indicateurs cles au-dessus du graphique."""
    stats = summarise(frame)
    columns = st.columns(6)

    columns[0].metric(
        "Dernier cours",
        format_amount(stats["last_close"], currency),
        delta=f"{stats['change_pct']:+.2f} %".replace(".", ",")
        if pd.notna(stats["change_pct"]) else None,
        help="Variation par rapport a la seance precedente.",
    )
    columns[1].metric(
        "Performance periode",
        f"{stats['period_change_pct']:+.2f} %".replace(".", ",")
        if pd.notna(stats["period_change_pct"]) else "-",
        help="Entre la premiere et la derniere seance affichee.",
    )
    columns[2].metric("Plus haut", format_amount(stats["highest"], currency))
    columns[3].metric("Plus bas", format_amount(stats["lowest"], currency))
    columns[4].metric(
        "Volume moyen", format_volume(stats["average_volume"]),
        help="Nombre de titres echanges par seance, en moyenne sur la periode.",
    )
    columns[5].metric(
        "Volatilite annualisee",
        f"{stats['volatility']:.1f} %".replace(".", ",")
        if pd.notna(stats["volatility"]) else "-",
        help="Ecart-type des rendements quotidiens, ramene a l'annee. "
             "Plus la valeur est elevee, plus le cours est agite.",
    )


def render_single(asset, frame: pd.DataFrame, controls: dict, theme: str) -> None:
    """Affiche une valeur : indicateurs, figure, donnees et export."""
    st.subheader(asset.label, help=f"{asset.sector} - {', '.join(asset.indices)}")

    if frame.empty:
        st.info("Aucune cotation sur la periode selectionnee.")
        return

    render_kpis(frame, asset.currency)

    enriched = with_indicators(
        frame,
        sma_windows=controls["sma"],
        ema_windows=controls["ema"],
        bollinger=20 if controls["bollinger"] else None,
    )
    overlays = tuple(
        [f"sma_{w}" for w in controls["sma"]]
        + [f"ema_{w}" for w in controls["ema"]]
        + (["bb_upper", "bb_lower"] if controls["bollinger"] else [])
    )

    figure = build_price_figure(
        enriched,
        label=asset.label,
        chart_type=controls["chart_type"],
        theme_name=theme,
        overlays=overlays,
        panels=controls["panels"],
        currency=asset.currency,
        log_scale=controls["log_scale"],
        hollow_candles=controls["hollow"],
    )
    st.plotly_chart(figure, use_container_width=True, config=PLOTLY_CONFIG)

    with st.expander("Donnees sous-jacentes et export"):
        table = frame.copy()
        table["date"] = table["date"].dt.date
        st.dataframe(
            table.iloc[::-1],
            use_container_width=True, hide_index=True, height=320,
            column_config={
                "date": st.column_config.DateColumn("Date", format="DD/MM/YYYY"),
                "open": st.column_config.NumberColumn("Ouverture", format="%.2f"),
                "high": st.column_config.NumberColumn("Plus haut", format="%.2f"),
                "low": st.column_config.NumberColumn("Plus bas", format="%.2f"),
                "close": st.column_config.NumberColumn("Cloture", format="%.2f"),
                "adj_close": st.column_config.NumberColumn("Cloture ajustee", format="%.2f"),
                "volume": st.column_config.NumberColumn("Volume", format="%d"),
                "dividends": st.column_config.NumberColumn("Dividende", format="%.4f"),
                "stock_splits": st.column_config.NumberColumn("Split", format="%.2f"),
            },
        )
        st.download_button(
            "Telecharger cette periode en CSV",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=f"{asset.slug}_{controls['chart_type'][:4].lower()}.csv",
            mime="text/csv",
            key=f"download_{asset.slug}",
        )


def render_comparison(series: dict, controls: dict, theme: str) -> None:
    """Compare les valeurs selectionnees, ramenees a une base commune."""
    frames = {
        asset.label: slice_period(frame, controls["date_range"])
        for asset, frame in series.items()
    }
    frames = {label: frame for label, frame in frames.items() if not frame.empty}

    if not frames:
        st.info("Aucune cotation sur la periode selectionnee.")
        return

    st.caption(
        "Chaque courbe est ramenee a 100 a sa premiere seance affichee. "
        "Un point a 120 signifie donc +20 % depuis le debut de la periode, "
        "quel que soit le prix ou la devise de la valeur."
    )
    figure = build_comparison_figure(frames, theme_name=theme)
    st.plotly_chart(figure, use_container_width=True, config=PLOTLY_CONFIG)

    board = pd.DataFrame(
        [
            {
                "Valeur": label,
                "Debut": frame["close"].iloc[0],
                "Fin": frame["close"].iloc[-1],
                "Performance (%)": (frame["close"].iloc[-1] / frame["close"].iloc[0] - 1) * 100,
                "Seances": len(frame),
            }
            for label, frame in frames.items()
        ]
    ).sort_values("Performance (%)", ascending=False)

    st.dataframe(
        board, use_container_width=True, hide_index=True,
        column_config={
            "Debut": st.column_config.NumberColumn(format="%.2f"),
            "Fin": st.column_config.NumberColumn(format="%.2f"),
            "Performance (%)": st.column_config.NumberColumn(format="%+.2f %%"),
        },
    )


def render_empty_state() -> None:
    """Ecran affiche tant qu'aucune donnee n'a ete collectee."""
    st.warning("Aucune donnee disponible : la collecte n'a pas encore ete lancee.")
    st.markdown(
        """
        Depuis la racine du projet :

        ```bash
        python -m scripts.update_data
        ```

        Le script telecharge les historiques declares dans `config/universe.json`
        et les ecrit dans `data/raw/`. Rechargez ensuite cette page.
        """
    )
    st.plotly_chart(
        empty_figure("En attente de donnees", chart_theme()),
        use_container_width=True, config=PLOTLY_CONFIG,
    )


def main() -> None:
    settings = get_settings()
    st.set_page_config(
        page_title=settings.app_title,
        page_icon="~",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title(settings.app_title)

    catalogue = cached_catalogue()
    if catalogue.empty:
        render_empty_state()
        return

    universe = load_universe()
    controls = sidebar_controls(catalogue, universe)
    theme = chart_theme()

    freshness = pd.to_datetime(catalogue["end_date"]).max()
    st.caption(
        f"{len(catalogue)} valeurs - {int(catalogue['rows'].sum()):,} cotations - "
        f"derniere seance : {freshness:%d/%m/%Y}. "
        "Source : Yahoo Finance, donnees de cloture non temps reel.".replace(",", " ")
    )

    if not controls["selection"]:
        st.info("Selectionnez au moins une valeur dans la barre laterale.")
        return

    series = {}
    for asset in controls["selection"]:
        try:
            series[asset] = cached_series(asset.ticker)
        except StorageError as exc:
            st.error(f"{asset.label} : {exc}")

    if not series:
        return

    if controls["is_comparison"]:
        render_comparison(series, controls, theme)
    elif len(series) == 1:
        asset, frame = next(iter(series.items()))
        render_single(asset, slice_period(frame, controls["date_range"]), controls, theme)
    else:
        tabs = st.tabs([asset.ticker for asset in series])
        for tab, (asset, frame) in zip(tabs, series.items(), strict=True):
            with tab:
                render_single(asset, slice_period(frame, controls["date_range"]), controls, theme)

    with st.expander("A propos des donnees"):
        st.markdown(
            f"""
            **Source** : Yahoo Finance, via la bibliotheque `yfinance`.
            Les cours sont des cotations de cloture, differees, fournies a titre
            informatif. Ce projet n'est pas un conseil en investissement.

            **Collecte** : `python -m scripts.update_data`
            (periode `{settings.period}`, intervalle `{settings.interval}`).
            L'application lit exclusivement les CSV de `data/raw/` : elle
            n'emet aucune requete reseau.

            **Colonnes disponibles** : date, ouverture, plus haut, plus bas,
            cloture, cloture ajustee, volume, dividendes, divisions d'action.
            Les quatre premieres suffisent a tracer un chandelier japonais.
            """
        )


if __name__ == "__main__":
    try:
        main()
    except (ConfigError, UniverseError) as exc:
        st.error(f"Configuration invalide : {exc}")
