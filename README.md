# Immo Radar

Outil personnel d'analyse d'investissement immobilier dans la vallée de Chamonix : collecte automatique des annonces, modèle de valorisation (AVM) entraîné sur les transactions réelles, et dashboard d'aide à la décision.

## Ce que ça fait

1. **Collecte** — un bot lit les emails d'alertes immobilières (IMAP) et en extrait prix, surface, commune, DPE, caractéristiques. Un scraper complémentaire peut enrichir les fiches des annonces prometteuses.
2. **Valorisation** — un modèle AVM (régression + XGBoost, entraîné sur les données publiques DVF de transactions) estime une *fair value* par bien et par commune. L'écart entre prix affiché et fair value fait ressortir les biens décotés.
3. **Scoring** — chaque annonce reçoit un score combinant rendement locatif estimé, décote à l'achat, potentiel de la commune et risques (DPE F/G, travaux, charges).
4. **Dashboard** — interface de suivi (version HTML générée + version React) : tri, filtres, insights par commune, estimateur interactif, simulateur de rendement à 20 ans avec revalorisation.

## Structure

```
bot.py / bot_overnight.py      Collecte des emails + scoring + génération du dashboard
scraper.py                     Enrichissement des annonces (Playwright / nodriver)
dvf_pipeline.py, dvf_model.py  Pipeline DVF -> features -> modèle de valorisation
build_avm_*.py, predict_avm.py Construction et application de l'AVM par segment
dashboard-react/               Dashboard React (Vite)
tools/                         Scripts one-shot d'itération sur le dashboard
config.example.json            Critères de recherche, communes, stratégie de scoring
.env.example                   Identifiants (jamais versionnés)
```

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env          # remplir ses identifiants
cp config.example.json config.json
python bot.py --config config.json --env .env
```

Les données DVF (transactions immobilières publiques, data.gouv.fr) sont à télécharger séparément dans `dvf/` — voir `dvf_pipeline.py`.

## Stack

Python (pandas, scikit-learn, XGBoost), SQLite, Playwright, React/Vite, Plotly.

## Note

Projet personnel d'apprentissage. Les données collectées restent locales (SQLite) ; aucune donnée d'annonce n'est redistribuée dans ce dépôt.
