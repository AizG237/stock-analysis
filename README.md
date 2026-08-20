# bourse-project

Collecte d'historiques boursiers **S&P 500 / Nasdaq 100 / CAC 40** depuis Yahoo
Finance, stockage en CSV, et application **Streamlit** d'exploration en
chandeliers japonais.

La separation est stricte et volontaire :

| Etage | Role | Reseau ? |
|---|---|---|
| `scripts/update_data.py` | telecharge et ecrit les CSV | oui, en local |
| `data/raw/*.csv` | historiques versionnes dans Git | - |
| `app.py` | lit les CSV et trace les graphiques | **non** |

L'application ne contacte jamais Yahoo Finance. C'est ce qui la rend deployable
sur Streamlit Cloud sans quota d'API, sans cle secrete et sans latence au
demarrage.

---

## Donnees collectees

126 series (122 actions + 4 indices de reference), 2 ans d'historique
journalier, soit environ 63 000 cotations pour 6 Mo de CSV.

Chaque fichier `data/raw/<SLUG>.csv` suit le meme schema :

| Colonne | Description |
|---|---|
| `date` | seance (AAAA-MM-JJ) |
| `open` | cours d'ouverture |
| `high` | plus haut de seance |
| `low` | plus bas de seance |
| `close` | cours de cloture |
| `adj_close` | cloture ajustee des dividendes et divisions |
| `volume` | titres echanges |
| `dividends` | dividende detache ce jour-la (0 sinon) |
| `stock_splits` | ratio de division d'action (0 sinon) |

Les quatre colonnes `open` / `high` / `low` / `close` sont exactement ce qu'il
faut pour tracer un chandelier japonais.

Le catalogue `data/metadata.csv` decrit chaque serie : nom, secteur, devise,
indices d'appartenance, nombre de lignes, bornes de dates, date de collecte.

### Convention de nommage des fichiers

Les symboles Yahoo passent mal en nom de fichier (`^` prefixe les indices, `.`
separe la place de cotation). Ils sont donc transposes :

| Symbole | Fichier |
|---|---|
| `AAPL` | `AAPL.csv` |
| `MC.PA` | `MC_PA.csv` |
| `^FCHI` | `IDX_FCHI.csv` |
| `BRK-B` | `BRK-B.csv` |

---

## Installation

Python 3.10 ou superieur.

```bash
git clone <url-du-depot>
cd bourse-project

python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # Windows : copy .env.example .env
```

> **yfinance >= 1.0 est obligatoire.** Les versions `0.2.x` n'arrivent plus a
> negocier le cookie/crumb impose par Yahoo Finance et retournent des series
> vides, sans message d'erreur clair.

---

## Utilisation

### 1. Collecter les donnees

```bash
python -m scripts.update_data
```

Options utiles :

```bash
# Un seul indice, sur cinq ans
python -m scripts.update_data --indices "CAC 40" --period 5y

# Quelques symboles precis, en hebdomadaire
python -m scripts.update_data --tickers AAPL MSFT MC.PA --interval 1wk

# Ecarter la seance du jour, encore en cours
python -m scripts.update_data --drop-incomplete

# Reprendre une collecte interrompue
python -m scripts.update_data --skip-existing

# Voir le perimetre sans rien telecharger
python -m scripts.update_data --list
```

`--help` liste l'ensemble des options.

### 2. Lancer l'application

```bash
streamlit run app.py
```

---

## Fonctionnalites de l'interface

**Selection**
- filtrage par indice, par secteur, puis par valeur
- inclusion optionnelle des indices eux-memes (^GSPC, ^NDX, ^FCHI, ^IXIC)
- plage de dates, et boutons 1M / 3M / 6M / 1A / Tout sur le graphique

**Types de graphique**
- chandeliers japonais (avec variante *bougies creuses*)
- ligne
- aire
- barres OHLC
- comparaison multi-valeurs en base 100

**Indicateurs**
- moyennes mobiles simples et exponentielles (5 a 200 seances)
- bandes de Bollinger
- panneaux d'analyse : volume, RSI (14), MACD

**Lecture**
- bandeau de six indicateurs cles : dernier cours, performance de periode,
  plus haut, plus bas, volume moyen, volatilite annualisee
- tableau des donnees sous-jacentes et export CSV de la periode affichee
- une valeur par onglet lorsque plusieurs sont selectionnees

---

## Configuration

Tout se regle dans `.env` (voir `.env.example` pour la documentation de chaque
cle). L'ordre de priorite est : variable d'environnement reelle > `.env` >
valeur par defaut du code. On peut donc surcharger ponctuellement :

```bash
BOURSE_PERIOD=5y python -m scripts.update_data
```

| Cle | Defaut | Role |
|---|---|---|
| `BOURSE_PERIOD` | `2y` | profondeur d'historique |
| `BOURSE_INTERVAL` | `1d` | granularite des bougies |
| `BOURSE_DATA_DIR` | `data` | racine de stockage |
| `BOURSE_MAX_WORKERS` | `4` | telechargements paralleles |
| `BOURSE_THROTTLE_SECONDS` | `0.4` | pause entre deux requetes |
| `BOURSE_RETRY_ATTEMPTS` | `3` | tentatives par symbole |
| `BOURSE_RETRY_BACKOFF` | `1.8` | facteur de backoff exponentiel |
| `BOURSE_LOG_LEVEL` | `INFO` | verbosite |
| `APP_TITLE` | - | titre de l'application |
| `APP_DEFAULT_TICKERS` | `AAPL,MSFT,MC.PA` | selection initiale |
| `APP_DEFAULT_CHART` | `Chandeliers japonais` | type de graphique initial |

`.env` n'est **jamais** versionne. Seul `.env.example` l'est.

---

## Modifier le perimetre suivi

L'univers n'est pas code en dur : il vit dans `config/universe.json`. Ajouter
une valeur consiste a ajouter un objet dans `assets` :

```json
{
  "ticker": "SAP.DE",
  "name": "SAP",
  "sector": "Technologie",
  "currency": "EUR",
  "indices": ["DAX"],
  "kind": "stock"
}
```

puis a relancer `python -m scripts.update_data --tickers SAP.DE`.

---

## Deploiement sur Streamlit Cloud

1. Verifier que `data/raw/` est bien versionne — Streamlit Cloud n'execute
   **pas** le script de collecte, il ne fait que servir les CSV du depot.

   ```bash
   python -m scripts.update_data --drop-incomplete
   git add data/ && git commit -m "donnees: mise a jour"
   git push
   ```

2. Sur [share.streamlit.io](https://share.streamlit.io), creer une application
   pointant sur le depot, branche `main`, fichier principal `app.py`.

3. Pour surcharger la configuration, ouvrir *App settings > Secrets* et y coller
   les cles au format TOML :

   ```toml
   APP_TITLE = "Mon tableau de bord boursier"
   APP_DEFAULT_TICKERS = "NVDA,TTE.PA"
   ```

   Streamlit expose les secrets de premier niveau comme variables
   d'environnement : `bourse/config.py` les lit sans modification.

**Mettre a jour les donnees en ligne** = relancer la collecte en local et
pousser le commit. Un `git push` redeploie automatiquement l'application.

---

## Organisation du code

```
bourse-project/
├── app.py                  application Streamlit (lecture seule)
├── bourse/
│   ├── config.py           configuration typee, chargee depuis .env
│   ├── universe.py         univers de valeurs, filtres, slugs de fichiers
│   ├── fetcher.py          telechargement Yahoo (lots + repli + backoff)
│   ├── storage.py          ecriture/lecture CSV, catalogue de metadonnees
│   ├── indicators.py       SMA, EMA, RSI, MACD, Bollinger, ATR, volatilite
│   └── charts.py           figures Plotly et jetons de couleur
├── config/universe.json    perimetre suivi (editable sans toucher au code)
├── scripts/update_data.py  collecte en ligne de commande
├── data/
│   ├── raw/*.csv           un fichier par valeur
│   └── metadata.csv        catalogue des series disponibles
├── tests/                  55 tests (unitaires + bout en bout Streamlit)
└── .streamlit/config.toml  theme de l'application
```

### Choix techniques

**Telechargement par lots.** `yfinance.download()` accepte plusieurs symboles
par appel : 20 symboles = 1 aller-retour reseau au lieu de 20, ce qui divise
d'autant le risque de limitation (HTTP 429). Les symboles revenus vides sont
ensuite retentes un par un.

**Ecriture atomique.** Chaque CSV est ecrit dans un `.tmp` puis renomme. Une
collecte interrompue ne laisse jamais de fichier tronque derriere elle.

**Un CSV par valeur.** Format lisible, diffable dans Git, et l'application ne
charge que les series effectivement consultees.

**Jamais de second axe Y superpose.** Volume, RSI et MACD occupent chacun leur
propre panneau sous les prix, avec un axe X partage. Superposer deux echelles
sur un meme trace fait apparaitre des correlations qui n'existent pas.

**Comparaison en base 100.** Comparer une action a 12 EUR et une autre a 900 USD
n'a de sens qu'en ramenant chaque serie a 100 a la premiere seance affichee.

**Palette validee daltonisme.** Les huit couleurs de serie ont ete verifiees en
protanopie, deuteranopie et tritanopie, en mode clair comme en mode sombre. La
hausse et la baisse utilisent le couple vert/rouge de statut, double d'un mode
*bougies creuses* pour ne pas reposer sur la seule couleur.

**Jours feries masques.** Masquer les seuls week-ends laisserait un trou a
chaque jour ferie de place. Les jours ouvres absents de la serie sont deduits et
masques a leur tour.

---

## Developpement

```bash
pip install -r requirements-dev.txt

pytest              # 55 tests
ruff check .        # lint
```

Les tests de `tests/test_app.py` utilisent `streamlit.testing.v1.AppTest` : ils
executent reellement `app.py` dans un runtime Streamlit sans navigateur, pilotent
les widgets et verifient qu'aucune exception ne remonte. Ils sont automatiquement
ignores tant que la collecte n'a pas ete lancee.

---

## Limites connues

- Yahoo Finance est une source gratuite **non contractuelle** : un symbole peut
  changer de code ou disparaitre sans preavis. Le script signale les echecs sans
  interrompre la campagne.
- La composition des indices evolue ; `config/universe.json` est un instantane a
  maintenir manuellement.
- L'intraday n'est pas gere : Yahoo ne le fournit que sur 60 jours glissants, ce
  qui n'a pas de sens pour un historique versionne.
- Une collecte lancee marche ouverte ramene une derniere bougie incomplete.
  Utiliser `--drop-incomplete` pour l'ecarter.

---

## Avertissement

Les cours sont des cotations de cloture differees, fournies a titre informatif.
Ce projet est un exercice technique : il ne constitue **pas** un conseil en
investissement.
