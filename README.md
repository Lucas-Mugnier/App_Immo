# Immo Radar / Alpestate

Je cherchais un appartement dans la vallée de Chamonix, alors j'ai fini par automatiser la recherche : un collecteur rassemble des annonces, un modèle estime une fair value à partir des transactions réelles (DVF), chaque bien est scoré et un dashboard React permet de tout comparer.

## Architecture

| Partie | Accès | Contenu |
|---|---|---|
| **Marché**, **S'instruire**, **Estimateur** | public | statistiques DVF, carte des ventes, estimateur AVM, contenus pédagogiques |
| **Biens**, **Comparateur**, **Analyse**, **Profil**, **Admin** | comptes invités | annonces en cours, scoring, simulation de rendement, corrections |

- Les annonces collectées ne sont **jamais** dans le code public : elles sont exportées dans `dashboard-react/private-data/` (gitignoré) puis publiées dans un bucket Supabase **privé**, lisible seulement par les emails de la table `allowed_users` (policies RLS dans `dashboard-react/supabase/setup.sql`).
- Le site (`dashboard-react/`) est un build Vite statique hébergé sur Vercel. Seules les données ouvertes (DVF) et des agrégats lissés y sont embarqués.

## Mettre à jour les annonces (depuis ce PC)

    .\refresh.ps1

Enchaîne `pipeline.py` (collecte puis export) et `dashboard-react/scripts/publish-data.mjs` (upload privé). Les comptes invités voient les nouvelles annonces immédiatement, sans redéploiement. Si des données publiques changent (`dashboard-react/src/data/`), commit + push pour redéployer.

## Installation

    pip install -r requirements.txt
    cd dashboard-react
    npm install
    copy .env.local.example .env.local       # URL + clé anon Supabase, email admin
    copy .env.publish.example .env.publish   # URL + clé service_role (local uniquement)
    npm run dev

Les données DVF (data.gouv.fr) sont à télécharger dans `dvf/` — voir `dvf_pipeline.py`. Les scripts de `tools/` retravaillent l'export.

## Gérer les invités

Supabase → SQL Editor : `insert into public.allowed_users (email) values ('...');` puis Authentication → Users → *Invite user*. Les inscriptions publiques sont désactivées.

## Note

Les annonces collectées restent privées (SQLite local + bucket privé). Aucune donnée d'annonce n'est redistribuée publiquement par ce dépôt ni par le site.
