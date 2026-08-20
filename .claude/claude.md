# bourse-project — repères pour Claude Code

Collecte d'historiques boursiers (Yahoo Finance) → CSV → application Streamlit.

## Commandes

```bash
.venv/Scripts/python.exe -m scripts.update_data     # collecte
.venv/Scripts/python.exe -m streamlit run app.py    # application
.venv/Scripts/python.exe -m pytest tests/ -q        # 55 tests
.venv/Scripts/python.exe -m ruff check .            # lint (doit rester vert)
```

## Règles d'architecture à respecter

- **`app.py` ne fait aucun appel réseau.** Il lit exclusivement `data/raw/*.csv`.
  Toute collecte passe par `scripts/update_data.py`, lancé en local.
- **`config/universe.json` est la source de vérité du périmètre.** Ne jamais
  coder un ticker en dur dans le code Python.
- **Jamais de second axe Y superposé** dans une figure : chaque mesure
  (volume, RSI, MACD) occupe son propre panneau via `make_subplots`.
- **Les couleurs de série viennent de `charts.LIGHT.series` / `DARK.series`**,
  affectées par rang fixe. Palette validée daltonisme : ne pas y toucher sans
  revalider (voir la compétence `dataviz`).
- **`yfinance` doit rester en version ≥ 1.0.** Les `0.2.x` renvoient des séries
  vides sans erreur explicite.
- L'écriture des CSV est atomique (`.tmp` puis `os.replace`) : conserver ce
  mécanisme dans `storage._atomic_write`.

## Conventions

- Code et docstrings en français, sans accents dans les fichiers `.py`
  (compatibilité des consoles Windows). Les fichiers Markdown sont accentués.
- Nommage des fichiers de données : `universe.slugify_ticker`
  (`MC.PA` → `MC_PA`, `^FCHI` → `IDX_FCHI`).
- Toute nouvelle option de configuration se déclare dans `.env.example`,
  se lit dans `bourse/config.py` et se documente dans le tableau du README.
