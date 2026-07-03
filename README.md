# Immo Radar

Je cherchais un appartement dans la vallée de Chamonix, alors j'ai fini par automatiser la recherche. Un bot lit mes alertes email immobilières, en extrait prix, surface, commune et DPE, estime une fair value à partir des transactions réelles (données DVF publiques), score chaque annonce et génère un dashboard pour tout comparer.

Concrètement :

- `bot.py` lit la boîte mail (IMAP), parse les annonces et alimente une base SQLite ; `scraper.py` peut enrichir les fiches des annonces prometteuses
- le modèle de valorisation (régression + XGBoost entraîné sur les données DVF, pipeline dans `dvf_pipeline.py` et `dvf_model.py`) estime une fair value par bien et par commune — l'écart avec le prix affiché fait ressortir les biens décotés
- le score combine rendement locatif estimé, décote à l'achat, potentiel de la commune et risques (DPE F/G, travaux, charges)
- le dashboard (HTML généré, plus une version React dans `dashboard-react/`) permet de trier et filtrer, avec insights par commune, estimateur interactif et simulateur de rendement à 20 ans

## Installation

    pip install -r requirements.txt
    cp .env.example .env                    # remplir ses identifiants mail
    cp config.example.json config.json      # critères de recherche
    python bot.py --config config.json --env .env

Les données DVF (transactions immobilières publiques, data.gouv.fr) sont à télécharger séparément dans `dvf/` — voir `dvf_pipeline.py`. Les scripts dans `tools/` sont des one-shots qui retravaillent le dashboard généré.

## Note

Les données collectées restent locales (SQLite). Aucune donnée d'annonce n'est redistribuée dans ce dépôt.
