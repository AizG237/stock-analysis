"""
Test de bout en bout de l'application Streamlit.

`AppTest` execute reellement `app.py` dans un runtime Streamlit sans navigateur :
les widgets sont pilotables, et toute exception levee par le script remonte dans
`at.exception`. C'est le seul moyen de verifier que l'interface fonctionne avec
les vraies donnees de `data/raw/`.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from bourse.storage import load_metadata

pytestmark = pytest.mark.skipif(
    load_metadata().empty,
    reason="aucune donnee collectee : lancer `python -m scripts.update_data`",
)

TIMEOUT = 90


def run_app() -> AppTest:
    app = AppTest.from_file("app.py", default_timeout=TIMEOUT)
    app.run()
    return app


def test_l_application_demarre_sans_exception():
    app = run_app()
    assert not app.exception, [e.value for e in app.exception]


def test_la_selection_par_defaut_affiche_des_indicateurs_cles():
    app = run_app()
    assert app.metric, "le bandeau d'indicateurs cles est vide"
    assert any("Dernier cours" in metric.label for metric in app.metric)


@pytest.mark.parametrize(
    "chart_type",
    ["Chandeliers japonais", "Ligne", "Aire", "OHLC (barres)", "Comparaison (base 100)"],
)
def test_chaque_type_de_graphique_se_rend_sans_erreur(chart_type):
    app = run_app()
    app.selectbox[0].set_value(chart_type).run()
    assert not app.exception, [e.value for e in app.exception]


def test_le_changement_de_valeur_ne_casse_pas_l_interface():
    app = run_app()
    valeurs = app.multiselect[2]  # 0 : indices, 1 : secteurs, 2 : valeurs
    options = valeurs.options
    assert options
    valeurs.set_value([options[0]]).run()
    assert not app.exception, [e.value for e in app.exception]


def test_les_panneaux_d_analyse_s_ajoutent_sans_erreur():
    app = run_app()
    app.multiselect[-1].set_value(["Volume", "RSI (14)", "MACD"]).run()
    assert not app.exception, [e.value for e in app.exception]
