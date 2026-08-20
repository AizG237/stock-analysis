"""
bourse
======

Bibliotheque de collecte et d'analyse de donnees boursieres (Yahoo Finance).

Organisation des modules
------------------------
- ``config``     : configuration typee, chargee depuis les variables d'environnement (.env)
- ``universe``   : univers de valeurs suivies (S&P 500 / Nasdaq 100 / CAC 40)
- ``fetcher``    : telechargement OHLCV depuis Yahoo Finance (avec reprise sur erreur)
- ``storage``    : ecriture / lecture des CSV et du catalogue de metadonnees
- ``indicators`` : indicateurs techniques (moyennes mobiles, RSI, MACD, Bollinger...)
- ``charts``     : figures Plotly (chandeliers japonais, ligne, aire, comparaison)
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
