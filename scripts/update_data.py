"""
Collecte des historiques boursiers et ecriture des CSV.

A executer en local (jamais sur Streamlit Cloud, qui ne fait que servir les CSV
deja presents dans le depot), puis a versionner :

    python -m scripts.update_data
    git add data/ && git commit -m "donnees: mise a jour du <date>"

Exemples
--------
    # Tout l'univers, avec la periode du .env
    python -m scripts.update_data

    # Un seul indice, sur cinq ans
    python -m scripts.update_data --indices "CAC 40" --period 5y

    # Quelques symboles precis, en hebdomadaire
    python -m scripts.update_data --tickers AAPL MSFT MC.PA --interval 1wk

    # Completer une collecte interrompue, sans retelecharger l'existant
    python -m scripts.update_data --skip-existing
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Permet `python scripts/update_data.py` autant que `python -m scripts.update_data`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bourse.config import (
    VALID_INTERVALS,
    VALID_PERIODS,
    ConfigError,
    configure_logging,
    get_settings,
)
from bourse.fetcher import fetch_assets
from bourse.storage import (
    StorageError,
    build_metadata_row,
    drop_current_session,
    has_data,
    save_prices,
    write_metadata,
)
from bourse.universe import Asset, UniverseError, load_universe

logger = logging.getLogger("scripts.update_data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update_data",
        description="Telecharge les historiques Yahoo Finance et les enregistre en CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--indices", nargs="+", metavar="NOM",
        help='Restreindre a un ou plusieurs indices (ex : --indices "CAC 40" "S&P 500").',
    )
    parser.add_argument(
        "--tickers", nargs="+", metavar="SYMBOLE",
        help="Restreindre a des symboles precis (ex : --tickers AAPL MC.PA).",
    )
    parser.add_argument(
        "--sectors", nargs="+", metavar="SECTEUR",
        help="Restreindre a un ou plusieurs secteurs.",
    )
    parser.add_argument(
        "--period", choices=VALID_PERIODS,
        help="Profondeur d'historique. Par defaut : BOURSE_PERIOD du .env.",
    )
    parser.add_argument(
        "--interval", choices=VALID_INTERVALS,
        help="Granularite des bougies. Par defaut : BOURSE_INTERVAL du .env.",
    )
    parser.add_argument(
        "--no-benchmarks", action="store_true",
        help="Ne pas collecter les indices de reference (^GSPC, ^FCHI...).",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Ignorer les valeurs dont le CSV existe deja.",
    )
    parser.add_argument(
        "--drop-incomplete", action="store_true",
        help="Ecarter la seance du jour, encore en cours (bougie partielle trompeuse).",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_only",
        help="Afficher l'univers selectionne et quitter, sans rien telecharger.",
    )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Verbosite. Par defaut : BOURSE_LOG_LEVEL du .env.",
    )
    return parser


def select_assets(args: argparse.Namespace) -> tuple[Asset, ...]:
    """Applique les filtres de la ligne de commande a l'univers declare."""
    universe = load_universe(include_benchmarks=not args.no_benchmarks)

    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers}
        selection = tuple(a for a in universe if a.ticker.upper() in wanted)
        unknown = wanted - {a.ticker.upper() for a in selection}
        if unknown:
            logger.warning("Symboles absents de l'univers, ignores : %s",
                           ", ".join(sorted(unknown)))
    else:
        selection = universe.filter(indices=args.indices, sectors=args.sectors)

    if args.skip_existing:
        before = len(selection)
        selection = tuple(a for a in selection if not has_data(a.ticker))
        logger.info("--skip-existing : %d valeurs deja presentes ignorees.",
                    before - len(selection))

    return selection


def _progress(done: int, total: int, label: str) -> None:
    """Barre de progression minimaliste, reecrite sur place."""
    width = 32
    filled = int(width * done / total)
    bar = "#" * filled + "." * (width - filled)
    sys.stdout.write(f"\r  [{bar}] {done:>3}/{total}  {label[:38]:<38}")
    sys.stdout.flush()
    if done == total:
        sys.stdout.write("\n")


def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_directories()

    assets = select_assets(args)
    if not assets:
        logger.error("Aucune valeur ne correspond aux filtres fournis.")
        return 1

    period = args.period or settings.period
    interval = args.interval or settings.interval

    if args.list_only:
        print(f"\n{len(assets)} valeurs selectionnees :\n")
        for asset in assets:
            print(f"  {asset.ticker:<10} {asset.name:<34} {', '.join(asset.indices)}")
        return 0

    print(f"\nCollecte de {len(assets)} valeurs | periode={period} | intervalle={interval}")
    print(f"Destination : {settings.raw_dir}\n")

    report = fetch_assets(assets, period=period, interval=interval,
                          settings=settings, on_progress=_progress)

    metadata_rows: list[dict] = []
    write_failures: list[tuple[str, str]] = []

    for result in report.succeeded:
        frame = result.frame
        if args.drop_incomplete:
            frame = drop_current_session(frame)
        try:
            save_prices(frame, result.asset.ticker)
        except StorageError as exc:
            write_failures.append((result.asset.ticker, str(exc)))
            continue
        # On relit le cadre normalise pour que le catalogue decrive exactement
        # ce qui a ete ecrit sur disque, et non le brut recu de Yahoo.
        from bourse.storage import load_prices

        stored = load_prices(result.asset.ticker)
        metadata_rows.append(build_metadata_row(result.asset, stored, interval))

    if metadata_rows:
        catalogue = write_metadata(metadata_rows)
        print(f"\nCatalogue mis a jour : {catalogue}")

    total_rows = sum(row["rows"] for row in metadata_rows)
    print(f"\n{'-' * 62}")
    print(f"  Series ecrites   : {len(metadata_rows)}/{len(assets)}")
    print(f"  Cotations totales: {total_rows:,}".replace(",", " "))

    problems = [
        (r.asset.ticker, r.error or "erreur inconnue") for r in report.failed
    ] + write_failures
    if problems:
        print(f"  Echecs           : {len(problems)}")
        for ticker, reason in problems:
            print(f"      - {ticker:<10} {reason}")
    print(f"{'-' * 62}\n")

    # Code 1 seulement si rien n'a pu etre collecte : quelques symboles retires
    # de la cote ne doivent pas faire echouer une integration continue.
    return 0 if metadata_rows else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        configure_logging(args.log_level)
        return run(args)
    except (ConfigError, UniverseError) as exc:
        logger.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        print("\nInterrompu par l'utilisateur.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
