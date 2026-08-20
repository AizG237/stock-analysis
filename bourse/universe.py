"""
Univers de valeurs suivies.

La liste des societes n'est pas codee en dur : elle est lue depuis
`config/universe.json`. Ajouter une valeur au suivi = ajouter une ligne dans ce
fichier, puis relancer `python -m scripts.update_data`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from bourse.config import get_settings

#: Caracteres non autorises (ou peu commodes) dans un nom de fichier.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


class UniverseError(RuntimeError):
    """Le fichier d'univers est absent, mal forme ou incoherent."""


def slugify_ticker(ticker: str) -> str:
    """Convertit un symbole Yahoo en nom de fichier portable.

    Yahoo utilise des symboles qui passent mal en nom de fichier selon les OS :
    `^` prefixe les indices, `.` separe la place de cotation.

    >>> slugify_ticker("AIR.PA")
    'AIR_PA'
    >>> slugify_ticker("^GSPC")
    'IDX_GSPC'
    >>> slugify_ticker("BRK-B")
    'BRK-B'
    """
    slug = ticker.strip().upper()
    if slug.startswith("^"):
        slug = "IDX_" + slug[1:]
    slug = slug.replace(".", "_")
    return _UNSAFE.sub("_", slug)


@dataclass(frozen=True, slots=True)
class Asset:
    """Une valeur suivie (action ou indice)."""

    ticker: str
    name: str
    sector: str
    currency: str
    indices: tuple[str, ...]
    kind: str  # "stock" | "index"

    @property
    def slug(self) -> str:
        return slugify_ticker(self.ticker)

    @property
    def label(self) -> str:
        """Libelle affiche dans l'interface : 'LVMH (MC.PA)'."""
        return f"{self.name} ({self.ticker})"

    @property
    def is_index(self) -> bool:
        return self.kind == "index"


@dataclass(frozen=True, slots=True)
class Universe:
    """Collection de valeurs, indexee par symbole."""

    assets: tuple[Asset, ...]
    index_meta: dict[str, dict[str, str]]

    # -- Acces -------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.assets)

    def __iter__(self):
        return iter(self.assets)

    @property
    def tickers(self) -> tuple[str, ...]:
        return tuple(asset.ticker for asset in self.assets)

    @property
    def index_names(self) -> tuple[str, ...]:
        """Noms d'indices, dans l'ordre de declaration du fichier de config."""
        return tuple(self.index_meta.keys())

    def get(self, ticker: str) -> Asset | None:
        """Retourne la valeur correspondant au symbole, ou None."""
        wanted = ticker.strip().upper()
        return next((a for a in self.assets if a.ticker.upper() == wanted), None)

    def require(self, ticker: str) -> Asset:
        """Comme `get`, mais leve une exception si le symbole est inconnu."""
        asset = self.get(ticker)
        if asset is None:
            raise UniverseError(f"Symbole inconnu dans l'univers : {ticker!r}")
        return asset

    # -- Filtres -----------------------------------------------------------

    def filter(
        self,
        *,
        indices: list[str] | tuple[str, ...] | None = None,
        sectors: list[str] | tuple[str, ...] | None = None,
        kinds: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[Asset, ...]:
        """Selectionne les valeurs correspondant a tous les criteres fournis."""
        selection = self.assets
        if indices:
            wanted = set(indices)
            selection = tuple(a for a in selection if wanted & set(a.indices))
        if sectors:
            wanted = set(sectors)
            selection = tuple(a for a in selection if a.sector in wanted)
        if kinds:
            wanted = set(kinds)
            selection = tuple(a for a in selection if a.kind in wanted)
        return selection

    def sectors(self) -> tuple[str, ...]:
        """Secteurs presents, tries alphabetiquement."""
        return tuple(sorted({a.sector for a in self.assets}))

    def to_frame(self) -> pd.DataFrame:
        """Vue tabulaire de l'univers, pratique pour l'affichage et les jointures."""
        return pd.DataFrame(
            [
                {
                    "ticker": a.ticker,
                    "slug": a.slug,
                    "name": a.name,
                    "sector": a.sector,
                    "currency": a.currency,
                    "indices": ", ".join(a.indices),
                    "kind": a.kind,
                }
                for a in self.assets
            ]
        )


def _parse_asset(record: dict, source: Path) -> Asset:
    missing = {"ticker", "name", "sector", "currency", "indices", "kind"} - record.keys()
    if missing:
        raise UniverseError(f"{source.name} : champs manquants {sorted(missing)} dans {record!r}")
    return Asset(
        ticker=str(record["ticker"]).strip().upper(),
        name=str(record["name"]).strip(),
        sector=str(record["sector"]).strip(),
        currency=str(record["currency"]).strip().upper(),
        indices=tuple(str(i).strip() for i in record["indices"]),
        kind=str(record["kind"]).strip().lower(),
    )


@lru_cache(maxsize=4)
def load_universe(path: Path | None = None, *, include_benchmarks: bool = True) -> Universe:
    """Charge et valide `config/universe.json`.

    Args:
        path: chemin alternatif vers le fichier d'univers (tests, variantes).
        include_benchmarks: inclure les indices de reference (^GSPC, ^FCHI...)
            en plus des actions.

    Raises:
        UniverseError: fichier absent, JSON invalide ou symbole duplique.
    """
    source = path or get_settings().universe_path
    if not source.exists():
        raise UniverseError(f"Fichier d'univers introuvable : {source}")

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UniverseError(f"{source.name} : JSON invalide ({exc})") from exc

    records = list(payload.get("assets", []))
    if include_benchmarks:
        records = list(payload.get("benchmarks", [])) + records

    assets = tuple(_parse_asset(r, source) for r in records)
    if not assets:
        raise UniverseError(f"{source.name} : aucune valeur declaree.")

    seen: set[str] = set()
    for asset in assets:
        if asset.ticker in seen:
            raise UniverseError(f"{source.name} : symbole duplique {asset.ticker!r}")
        seen.add(asset.ticker)

    return Universe(assets=assets, index_meta=dict(payload.get("indices", {})))
