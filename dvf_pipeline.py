#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dvf_pipeline.py -- Chargement, nettoyage, enrichissement et stats DVF dept 74
Produit:
  dvf/dvf_clean.csv       -- transactions nettoyees + has_parking + geo optionnel
  dvf/dvf_stats.json      -- stats par commune/section/annee (avec parking_pct)
  dvf/dvf_geo_cache.json  -- cache geocodage IGN (adresse -> [lat, lon])
  dvf/dvf_alt_cache.json  -- cache altimetrie IGN ([lat4,lon4] -> altitude)

Usage:
  C:/Users/lucas/anaconda3/python.exe dvf_pipeline.py          # stats seules
  C:/Users/lucas/anaconda3/python.exe dvf_pipeline.py --geo    # + geocodage + alti
  C:/Users/lucas/anaconda3/python.exe dvf_pipeline.py --geo --geo-max 500
"""

import csv
import json
import math
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from collections import defaultdict, Counter
from datetime import datetime

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("ERREUR: pandas/numpy manquant. Lancer avec:")
    print("  C:/Users/lucas/anaconda3/python.exe dvf_pipeline.py")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DVF_DIR  = os.path.join(BASE_DIR, "dvf")

DVF_FILES = [
    os.path.join(DVF_DIR, f"ValeursFoncieres-{y}.txt")
    for y in range(2021, 2026)
]

OUTPUT_CLEAN  = os.path.join(DVF_DIR, "dvf_clean.csv")
OUTPUT_STATS  = os.path.join(DVF_DIR, "dvf_stats.json")
OUTPUT_GEO    = os.path.join(DVF_DIR, "dvf_geo_cache.json")
OUTPUT_ALT    = os.path.join(DVF_DIR, "dvf_alt_cache.json")

TARGET_COMMUNES = {
    "CHAMONIX MONT BLANC",
    "DOMANCY",
    "LES HOUCHES",
    "PASSY",
    "SALLANCHES",
    "SERVOZ",
    "SAINT GERVAIS LES BAINS",
}

COMMUNE_DISPLAY = {
    "CHAMONIX MONT BLANC":     "Chamonix-Mont-Blanc",
    "DOMANCY":                 "Domancy",
    "LES HOUCHES":             "Les Houches",
    "PASSY":                   "Passy",
    "SALLANCHES":              "Sallanches",
    "SERVOZ":                  "Servoz",
    "SAINT GERVAIS LES BAINS": "Saint-Gervais-les-Bains",
}

# Coordonnees centres communes (lat, lon) - pour dist_centre_km
COMMUNE_CENTERS = {
    "CHAMONIX MONT BLANC":     (45.9237, 6.8694),
    "DOMANCY":                 (45.8928, 6.6867),
    "LES HOUCHES":             (45.8999, 6.8037),
    "PASSY":                   (45.9178, 6.6949),
    "SALLANCHES":              (45.9386, 6.6346),
    "SERVOZ":                  (45.9334, 6.7792),
    "SAINT GERVAIS LES BAINS": (45.8925, 6.7028),
}

# Seuils de qualite globaux
MIN_SURFACE = 9      # m2
MAX_SURFACE = 400    # m2
MIN_PRIX_M2 = 800    # e/m2 (plancher global, remplace par MIN_PRIX_M2_COMMUNE si plus eleve)
MAX_PRIX_M2 = 60000  # e/m2
MIN_PRIX    = 15000  # e

# Planchers de prix par commune (marche libre - exclu HLM, viager, ventes entre proches)
# Confirme par user (expert marche local).
# NB: Chamonix maisons -> floor 8000 (vieilles grandes maisons <8k sont ventes familiales/successions)
#     Chamonix apparts -> floor 6000 (petits studios 14-35m2 se vendent legitimement a 6-7k)
MIN_PRIX_M2_COMMUNE = {
    "CHAMONIX MONT BLANC":     6000,   # appart (surcharge maison ci-dessous)
    "LES HOUCHES":             3800,
    "SAINT GERVAIS LES BAINS": 2500,
    "SERVOZ":                  2000,
    "PASSY":                   1500,
    "DOMANCY":                 1800,
    "SALLANCHES":              1200,
}

# Plancher specifique MAISON par commune (plus restrictif que appart)
# Chamonix: vieilles grandes maisons <8k€/m2 sont quasi-toutes successions/ventes familiales
# Les Houches/St Gervais: meme logique mais seuil plus bas (marche moins tendu)
MIN_PRIX_M2_MAISON = {
    "CHAMONIX MONT BLANC":     8000,
    "LES HOUCHES":             4500,
    "SAINT GERVAIS LES BAINS": 3500,
    "SERVOZ":                  2500,
    "PASSY":                   1800,
    "DOMANCY":                 2000,
    "SALLANCHES":              1500,
}

# Filtres qualite supplementaires
MAX_NB_LOTS_RESIDENTIEL = 5   # ventes en bloc (immeuble entier) = hors marche individuel

# APIs
IGN_GEOCODE_URL  = "https://data.geopf.fr/geocodage/search"
TOPO_URL         = "https://api.opentopodata.org/v1/srtm90m"  # batch, 100 pts/req
GEO_DELAY        = 0.12   # s entre appels geocodage
ALT_DELAY        = 1.1    # s entre batches altimetrie (rate limit 1 req/s)
ALT_BATCH        = 100    # points par batch altimetrie
GEO_MAX_NEW      = 3000   # max nouvelles adresses geocodees par run

# Fichier cache remontees mecaniques (genere une seule fois)
OUTPUT_SKI   = os.path.join(DVF_DIR, "ski_lifts_osm.json")
OUTPUT_PLU   = os.path.join(DVF_DIR, "dvf_plu_cache.json")

# Types aerialway = remontees utiles (exclut pylons, zip_line, goods...)
SKI_LIFT_TYPES = {"station", "gondola", "cable_car", "chair_lift", "drag_lift",
                  "platter", "t-bar", "mixed_lift", "magic_carpet", "rope_tow", "j-bar"}

# ── Colonnes DVF (index 0-based) ──────────────────────────────────────────────
COL = {
    "id_doc":        0,
    "no_disp":       7,
    "date":          8,
    "nature":        9,
    "valeur":        10,
    "no_voie":       11,
    "type_voie":     13,
    "voie":          15,
    "cp":            16,
    "commune":       17,
    "dept":          18,
    "code_commune":  19,
    "section":       21,
    "no_plan":       22,
    "nb_lots":       34,
    "code_type":     35,
    "type_local":    36,
    "surface":       38,
    "pieces":        39,
    "surf_terrain":  42,  # surface terrain (maison seulement, ~93% rempli)
    # Surfaces Carrez des lots de la mutation (appart seulement, loi Carrez)
    # cols 25,27,29,31,33 = Carrez des lots 1-5. Dependances ont Carrez=0.
    "carrez_1": 25, "carrez_2": 27, "carrez_3": 29, "carrez_4": 31, "carrez_5": 33,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_float_fr(s: str):
    if not s or not s.strip():
        return None
    s = s.strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def parse_int(s: str):
    if not s or not s.strip():
        return None
    try:
        return int(s.strip())
    except ValueError:
        return None

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance haversine en km entre deux points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ── Phase 1: Chargement et filtrage ──────────────────────────────────────────
# Note: DVF post-2019 -> id_doc/ref_doc anonymises (toujours vides).
# On traite chaque ligne residentielle comme transaction independante.
#
# Detection parking (has_parking):
#   Chaque mutation incluant un local residentiel ET une dependance (type=3)
#   est detectee via la cle (date, commune, valeur_brute).
#   Le prix/m2 brut inclut alors la valeur du parking (~100-150k€ selon commune).
#   has_parking=1 est ajoute comme feature au modele pour capturer ce biais.

def load_dvf() -> pd.DataFrame:
    print("=" * 60)
    print("Phase 1: Chargement DVF dept 74")
    print("=" * 60)

    # --- Passe unique: collecter toutes les lignes pertinentes ---
    parking_counter  = Counter()        # mutation_key -> nb dependances
    commercial_set   = set()            # mutations mixtes residentiel+commercial -> exclure
    dep_terrain      = defaultdict(dict) # mutation_key -> {noplan: terrain_m2}
    # Chaque parcelle cadastrale (noplan) n'est comptee qu'une fois par mutation.
    # Evite le double-comptage quand maison + dependances partagent le meme noplan.
    residential      = []               # lignes type 1 (maison) / 2 (appart)

    for fpath in DVF_FILES:
        if not os.path.exists(fpath):
            print(f"  WARN: {fpath} introuvable")
            continue

        year = int(os.path.basename(fpath).split("-")[1].split(".")[0])
        print(f"  Lecture {os.path.basename(fpath)}...", end=" ", flush=True)
        n_before = len(residential)

        with open(fpath, encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter="|")
            next(reader)
            for row in reader:
                if len(row) < 40:
                    continue
                if row[COL["dept"]].strip() != "74":
                    continue
                commune = row[COL["commune"]].strip()
                if commune not in TARGET_COMMUNES:
                    continue
                if row[COL["nature"]].strip() != "Vente":
                    continue

                code_type  = row[COL["code_type"]].strip()
                date_str   = row[COL["date"]].strip()
                valeur_raw = row[COL["valeur"]].strip()

                # Dependances (parking, garage, cave, mazot...)
                if code_type == "3":
                    mk = (date_str, commune, valeur_raw)
                    parking_counter[mk] += 1
                    # Stocker terrain par noplan pour eviter de compter 2x la meme parcelle
                    noplan = row[COL["no_plan"]].strip() if len(row) > COL["no_plan"] else ""
                    st_dep = row[COL["surf_terrain"]] if len(row) > COL["surf_terrain"] else ""
                    st_dep_val = parse_float_fr(st_dep)
                    if st_dep_val and st_dep_val > 0:
                        dep_key = noplan if noplan else f"dep_{parking_counter[mk]}_{st_dep_val}"
                        dep_terrain[mk][dep_key] = st_dep_val
                    continue

                # Local commercial/industriel UNIQUEMENT (code_type="4"):
                # flaguer la mutation pour exclusion (prix inclut valeur commerciale)
                # NB: code_type="" = parcelle terrain agricole/nature -> PAS commercial, ignorer
                if code_type == "4":
                    commercial_set.add((date_str, commune, valeur_raw))
                    continue

                valeur  = parse_float_fr(valeur_raw)
                surface = parse_float_fr(row[COL["surface"]])
                pieces  = parse_int(row[COL["pieces"]])

                if not valeur or valeur < MIN_PRIX:
                    continue
                if not surface or surface <= 0:
                    # Parcelle terrain sans batiment (code_type="", surface=0):
                    # stocker par noplan pour eviter double-comptage
                    if code_type == "":
                        noplan = row[COL["no_plan"]].strip() if len(row) > COL["no_plan"] else ""
                        st_raw = row[COL["surf_terrain"]] if len(row) > COL["surf_terrain"] else ""
                        st_val = parse_float_fr(st_raw)
                        if st_val and st_val > 0:
                            mk = (date_str, commune, valeur_raw)
                            dep_key = noplan if noplan else f"par_{st_val}"
                            dep_terrain[mk][dep_key] = st_val
                    continue

                try:
                    d = datetime.strptime(date_str, "%d/%m/%Y")
                    annee = d.year
                    mois  = d.month
                except Exception:
                    annee = year
                    mois  = 0

                nb_lots_raw      = row[COL["nb_lots"]]      if len(row) > COL["nb_lots"]      else ""
                surf_terrain_raw = row[COL["surf_terrain"]] if len(row) > COL["surf_terrain"] else ""

                # Surface Carrez (apparts seulement): somme des lots Carrez non-nuls
                # Les dependances (parking/cave) ont Carrez=0 -> exclues automatiquement
                surf_carrez = None
                if code_type == "2":
                    carrez_parts = []
                    for ck in ["carrez_1","carrez_2","carrez_3","carrez_4","carrez_5"]:
                        v = parse_float_fr(row[COL[ck]]) if len(row) > COL[ck] else None
                        if v and v > 1:
                            carrez_parts.append(v)
                    if carrez_parts:
                        surf_carrez = sum(carrez_parts)
                        # Sanity: Carrez ne peut pas depasser surface reelle
                        if surface and surf_carrez > surface * 1.05:
                            surf_carrez = None

                residential.append({
                    "date":         date_str,
                    "annee":        annee,
                    "mois":         mois,
                    "commune":      commune,
                    "code_commune": row[COL["code_commune"]].strip(),
                    "section":      row[COL["section"]].strip().upper(),
                    "no_plan":      row[COL["no_plan"]].strip(),
                    "no_voie":      row[COL["no_voie"]].strip(),
                    "type_voie":    row[COL["type_voie"]].strip(),
                    "voie":         row[COL["voie"]].strip(),
                    "cp":           row[COL["cp"]].strip(),
                    "valeur":       valeur,
                    "surface":      surface,
                    "pieces":       pieces if pieces and 1 <= pieces <= 15 else None,
                    "type_local":   "appart" if code_type == "2" else "maison",
                    "code_type":    int(code_type),
                    "nb_lots":      parse_int(nb_lots_raw) or 0,
                    "surf_terrain": parse_float_fr(surf_terrain_raw),  # maison ET appart (appart avec terrain = vente groupee a exclure du modele)
                    "surf_carrez":  surf_carrez,
                    # Cles internes pour detection parking (supprimees apres)
                    "_date_key":   date_str,
                    "_commune_key": commune,
                    "_valeur_key":  valeur_raw,
                })

        print(f"{len(residential) - n_before:,} lignes")

    print(f"\n  Dependances (parking/cave) detectees: {len(parking_counter):,} cles uniques")
    print(f"  Mutations mixtes residentiel+commercial: {len(commercial_set):,} (a exclure)")
    print(f"  Mutations avec terrain dependance: {len(dep_terrain):,}")
    print(f"  Total residentiel avant filtres: {len(residential):,}")

    # --- Enrichissement: parking, terrain dependance, flag commercial ---
    n_with_parking = 0
    n_commercial_excluded = 0
    n_dep_terrain_added = 0
    residential_clean = []
    for r in residential:
        key = (r["_date_key"], r["_commune_key"], r["_valeur_key"])

        # Exclure mutations mixtes avec local commercial/industriel
        if key in commercial_set:
            n_commercial_excluded += 1
            del r["_date_key"]; del r["_commune_key"]; del r["_valeur_key"]
            continue

        r["n_dependances"] = parking_counter.get(key, 0)
        r["has_parking"]   = 1 if r["n_dependances"] > 0 else 0
        if r["has_parking"]:
            n_with_parking += 1

        # Ajouter terrain des dependances / parcelles separees (maisons uniquement)
        # Exclure le noplan de la maison elle-meme (terrain deja compte dans surf_terrain)
        if r.get("type_local") == "maison" and key in dep_terrain:
            maison_noplan = r.get("no_plan", "")
            extra = sum(
                v for np_key, v in dep_terrain[key].items()
                if np_key != maison_noplan
            )
            if extra > 0:
                current = r.get("surf_terrain") or 0
                r["surf_terrain"] = (current or 0) + extra
                n_dep_terrain_added += 1

        del r["_date_key"]; del r["_commune_key"]; del r["_valeur_key"]
        residential_clean.append(r)

    residential = residential_clean
    print(f"  Exclusions commercial: {n_commercial_excluded:,}")
    print(f"  Terrains dependance ajoutes: {n_dep_terrain_added:,}")
    n_with_parking = sum(1 for r in residential if r.get("has_parking"))

    pct_parking = n_with_parking / max(len(residential), 1) * 100
    print(f"  has_parking=1: {n_with_parking:,} ({pct_parking:.0f}%)")

    df = pd.DataFrame(residential)
    if df.empty:
        print("ERREUR: aucune donnee trouvee!")
        sys.exit(1)

    # ── Consolidation multi-lots ─────────────────────────────────────────────
    # DVF enregistre une ligne par (lot_habitation × parcelle_terrain) pour
    # la meme mutation notariale. Cas possibles:
    #   A) 1 logement × N parcelles  → meme surface, N terrains differents
    #   B) N logements × M parcelles → produit cartesien (N×M lignes)
    #
    # Exemple cas B (DES RIVES 15/06/2022):
    #   22m²/63m², 22m²/535m², 54m²/63m², 54m²/535m²  → prix=1 568 200€
    #   Surface reelle = 22+54=76m²  |  Terrain = 63+535=598m²
    #   prix/m2 correct = 20 634 €/m² (vs 29 041€ si on prend 54m² seul)
    #
    # Solution: groupe par (date, commune, valeur, voie) sans surface dans la cle
    #   - surface   = somme des valeurs UNIQUES (evite de compter N fois chaque lot)
    #   - surf_terrain = somme des valeurs UNIQUES (evite de compter M fois chaque parcelle)
    n_before_dedup = len(df)
    dedup_key = ["date", "commune", "valeur", "voie"]
    df["surf_terrain"] = pd.to_numeric(df["surf_terrain"], errors="coerce").fillna(0)
    df["surface"]      = pd.to_numeric(df["surface"],      errors="coerce").fillna(0)

    def sum_unique(s):
        """Somme des valeurs uniques (ignore doublons du produit cartesien)."""
        return s.dropna().unique().sum()

    # Colonnes speciales: somme des uniques
    sum_unique_cols = {"surf_terrain": sum_unique, "surface": sum_unique}
    # Colonnes pieces: prendre le max (lot principal)
    max_cols = {"pieces": "max"}
    # Tout le reste: premier
    first_cols = {c: "first" for c in df.columns
                  if c not in dedup_key + list(sum_unique_cols) + list(max_cols)}
    agg_dict = {**first_cols, **sum_unique_cols, **max_cols}
    df = df.groupby(dedup_key, as_index=False, sort=False).agg(agg_dict)

    # Nettoyage: 0 → NaN pour terrain; surface 0 = invalide
    df["surf_terrain"] = df["surf_terrain"].replace(0, float("nan"))
    df = df[df["surface"] > 0].copy()

    n_dedup = n_before_dedup - len(df)
    print(f"  Consolidation multi-lots: {n_dedup:,} lignes fusionnees ({n_before_dedup:,} -> {len(df):,})")

    # Calcul prix/m2 brut (inclut valeur parking si has_parking=1)
    df["prix_m2"] = df["valeur"] / df["surface"]

    # Filtres qualite (structurels uniquement - pas de filtre prix)
    print("\nPhase 1b: Filtres qualite...")
    n0 = len(df)

    # Garder filtres structurels: surface aberrante, prix minimal absolu, ventes en bloc
    mask = (
        (df["surface"] >= MIN_SURFACE) &
        (df["surface"] <= MAX_SURFACE) &
        (df["valeur"]  >= MIN_PRIX) &
        (df["nb_lots"] <= MAX_NB_LOTS_RESIDENTIEL)  # exclure ventes en bloc immeuble entier
    )
    df_clean = df[mask].copy()

    # Filtres qualitatifs maisons
    # Une "maison" doit avoir un terrain ou une dépendance pour etre credible.
    # Sans rien: probablement mazot, cabanon, local mixte, erreur de saisie DVF.
    st_ok  = df_clean["surf_terrain"].notna() & (df_clean["surf_terrain"] > 50)
    dep_ok = df_clean["n_dependances"].fillna(0) > 0
    has_land = st_ok | dep_ok

    # 1) Maison < 30m² = trop petite pour etre une vraie maison (mazot, box)
    too_small = (df_clean["type_local"] == "maison") & (df_clean["surface"] < 30)

    # 2) Maison < 65m² sans terrain ni dependance = suspect (cabanon, misclassified)
    suspect_small = (
        (df_clean["type_local"] == "maison") &
        (df_clean["surface"] < 65) &
        ~has_land
    )

    # 3) Maison 1 piece > 80m² sans terrain = gite/local mixte
    suspect_large1p = (
        (df_clean["type_local"] == "maison") &
        (df_clean["surface"] > 80) &
        (df_clean["pieces"].fillna(0) <= 1) &
        ~has_land
    )

    # 4) Toute maison sans terrain ni dependance = impossible (apres recuperation parcelles)
    #    Un terrain peut etre dans une parcelle separee → deja recollecte plus haut.
    #    Si toujours 0 ici: erreur DVF / local commercial mal classifie.
    suspect_no_terrain = (
        (df_clean["type_local"] == "maison") &
        ~has_land
    )

    bad_maison = too_small | suspect_small | suspect_large1p | suspect_no_terrain
    n_bad = int(bad_maison.sum())
    df_clean = df_clean[~bad_maison].copy()
    if n_bad > 0:
        print(f"  Maisons suspectes (mazot/cabanon/sans terrain): {n_bad:,} supprimees")

    n_removed = n0 - len(df_clean)
    print(f"  {n_removed:,} filtres structurels (surface/valeur/lots) -> {len(df_clean):,} transactions")
    print(f"  Total conserve: {len(df_clean):,} transactions")

    print(f"\n  Repartition par commune:")
    for com, cnt in df_clean["commune"].value_counts().items():
        dfc = df_clean[df_clean["commune"] == com]
        med = dfc["prix_m2"].median()
        pk  = dfc["has_parking"].mean() * 100
        print(f"    {com}: {cnt:,} | mediane {med:,.0f} e/m2 | parking {pk:.0f}%")

    return df_clean

# ── Phase 2: Statistiques ─────────────────────────────────────────────────────

def compute_stats(df: pd.DataFrame) -> dict:
    print("\n" + "=" * 60)
    print("Phase 2: Calcul des statistiques")
    print("=" * 60)

    stats = {
        "generated_at":       datetime.now().isoformat(),
        "total_transactions": int(len(df)),
        "annees":             sorted(df["annee"].unique().tolist()),
        "communes":           {},
    }

    years_all = sorted(df["annee"].unique())

    for commune in sorted(TARGET_COMMUNES):
        dfc = df[df["commune"] == commune].copy()
        if dfc.empty:
            continue

        display  = COMMUNE_DISPLAY.get(commune, commune)
        n_total  = len(dfc)
        pm2_all  = dfc["prix_m2"].dropna()

        median_global = float(pm2_all.median())
        q1     = float(pm2_all.quantile(0.25))
        q3     = float(pm2_all.quantile(0.75))
        mean_  = float(pm2_all.mean())

        # Parking pct
        parking_pct = round(float(dfc["has_parking"].mean() * 100), 1) if "has_parking" in dfc.columns else None

        # Par annee
        by_year_data  = {}
        years_medians = {}
        for yr in years_all:
            dfy = dfc[dfc["annee"] == yr]["prix_m2"].dropna()
            if len(dfy) >= 5:
                m = float(dfy.median())
                by_year_data[str(yr)] = {
                    "median_m2": round(m),
                    "n":         int(len(dfy)),
                    "q1":        round(float(dfy.quantile(0.25))),
                    "q3":        round(float(dfy.quantile(0.75))),
                }
                years_medians[yr] = m

        # CAGR
        cagr_pct  = None
        trend_pct = None
        yr_sorted = sorted(years_medians.keys())
        if len(yr_sorted) >= 2:
            yr_first, yr_last = yr_sorted[0], yr_sorted[-1]
            m_first, m_last   = years_medians[yr_first], years_medians[yr_last]
            n_years = yr_last - yr_first
            if n_years > 0 and m_first > 0:
                cagr_pct  = round((m_last / m_first) ** (1 / n_years) - 1, 4) * 100
                trend_pct = round((m_last - m_first) / m_first * 100, 1)

        # Par section
        by_section = {}
        for sec in sorted(dfc["section"].dropna().unique()):
            dfs = dfc[dfc["section"] == sec]["prix_m2"].dropna()
            if len(dfs) < 5:
                continue
            sec_years = {}
            for yr in years_all:
                dfsy = dfc[(dfc["section"] == sec) & (dfc["annee"] == yr)]["prix_m2"].dropna()
                if len(dfsy) >= 3:
                    sec_years[str(yr)] = {
                        "median_m2": round(float(dfsy.median())),
                        "n":         int(len(dfsy)),
                    }
            sec_medians = {int(y): d["median_m2"] for y, d in sec_years.items()}
            sec_cagr = None
            if len(sec_medians) >= 2:
                sy = sorted(sec_medians.keys())
                m0, m1 = sec_medians[sy[0]], sec_medians[sy[-1]]
                ny = sy[-1] - sy[0]
                if ny > 0 and m0 > 0:
                    sec_cagr = round((m1 / m0) ** (1 / ny) - 1, 4) * 100
            by_section[sec] = {
                "median_m2": round(float(dfs.median())),
                "q1_m2":     round(float(dfs.quantile(0.25))),
                "q3_m2":     round(float(dfs.quantile(0.75))),
                "n":         int(len(dfs)),
                "cagr_pct":  round(sec_cagr, 1) if sec_cagr else None,
                "by_year":   sec_years,
            }

        # Par type
        by_type = {}
        for typ in ("appart", "maison"):
            dft = dfc[dfc["type_local"] == typ]["prix_m2"].dropna()
            if len(dft) >= 5:
                by_type[typ] = {
                    "median_m2": round(float(dft.median())),
                    "n":         int(len(dft)),
                    "q1_m2":     round(float(dft.quantile(0.25))),
                    "q3_m2":     round(float(dft.quantile(0.75))),
                }

        # Par surface bracket
        def surface_bracket(s):
            if s < 30:  return "<30m²"
            if s < 50:  return "30-50m²"
            if s < 70:  return "50-70m²"
            if s < 100: return "70-100m²"
            return "100m²+"

        dfc["surface_cat"] = dfc["surface"].apply(surface_bracket)
        by_surface = {}
        for cat in ["<30m²", "30-50m²", "50-70m²", "70-100m²", "100m²+"]:
            dft = dfc[dfc["surface_cat"] == cat]["prix_m2"].dropna()
            if len(dft) >= 3:
                by_surface[cat] = {"median_m2": round(float(dft.median())), "n": int(len(dft))}

        # Distribution
        pm2_sorted   = sorted(pm2_all.tolist())
        step         = max(1, len(pm2_sorted) // 50)
        distribution = [round(x) for x in pm2_sorted[::step]]

        commune_stats = {
            "display":      display,
            "n":            n_total,
            "median_m2":    round(median_global),
            "q1_m2":        round(q1),
            "q3_m2":        round(q3),
            "mean_m2":      round(mean_),
            "cagr_pct":     round(cagr_pct, 1) if cagr_pct else None,
            "trend_pct":    trend_pct,
            "parking_pct":  parking_pct,
            "by_year":      by_year_data,
            "by_section":   by_section,
            "by_type":      by_type,
            "by_surface":   by_surface,
            "distribution": distribution,
        }
        stats["communes"][commune] = commune_stats

        print(f"\n  {display}:")
        print(f"    n={n_total} | mediane={round(median_global):,} e/m2 "
              f"| Q1={round(q1):,} Q3={round(q3):,}")
        if parking_pct is not None:
            print(f"    Parking bundle: {parking_pct:.1f}% des transactions")
        if trend_pct:
            cagr_str = f"  CAGR {cagr_pct:.1f}%/an" if cagr_pct else ""
            print(f"    Tendance: {trend_pct:+.1f}% sur {yr_sorted[0]}-{yr_sorted[-1]}{cagr_str}")
        if by_section:
            parts = [f"{s}={v['median_m2']:,}e/m2" for s, v in list(by_section.items())[:5]]
            print(f"    Sections: {', '.join(parts)}")

    return stats

# ── Phase 3a: Geocodage IGN ───────────────────────────────────────────────────

def geocode_ign(address: str):
    """Geocode via IGN Geoplateforme. Retourne (lat, lon) ou None."""
    params = urllib.parse.urlencode({"q": address, "limit": "1"})
    url = f"{IGN_GEOCODE_URL}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "appart-alert-dvf/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        features = data.get("features", [])
        if not features:
            return None
        coords = features[0]["geometry"]["coordinates"]  # [lon, lat]
        score  = features[0]["properties"].get("score", 0)
        if score < 0.4:
            return None
        return (round(coords[1], 6), round(coords[0], 6))  # (lat, lon)
    except Exception:
        return None

# ── Phase 3b: Altimetrie OpenTopoData (SRTM 90m, batch 100) ─────────────────

def get_altitudes_batch(coords: list) -> list:
    """
    Requete altitude en batch via OpenTopoData SRTM90m.
    coords: liste de (lat, lon)
    Retourne: liste de float|None, meme ordre que coords.
    Rate limit: 1 req/s, max 100 points/req.
    """
    if not coords:
        return []
    loc_str = "|".join(f"{lat},{lon}" for lat, lon in coords)
    url = f"{TOPO_URL}?locations={loc_str}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "appart-alert-dvf/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        results = data.get("results", [])
        out = []
        for r in results:
            elev = r.get("elevation")
            out.append(float(elev) if elev is not None and elev > -1000 else None)
        return out
    except Exception:
        return [None] * len(coords)

# ── Phase 3: Geocodage + Altimetrie + Features geo ───────────────────────────

def run_geocoding(df: pd.DataFrame, geo_max: int = GEO_MAX_NEW) -> pd.DataFrame:
    """
    Geocode les transactions, requete altitude, calcule dist_centre_km.
    Toutes les donnees sont mises en cache JSON pour runs futurs.
    """
    print("\n" + "=" * 60)
    print("Phase 3: Geocodage + Altimetrie IGN")
    print("=" * 60)

    # ── 3a: Geocodage ────────────────────────────────────────────────────────
    geo_cache: dict = {}
    if os.path.exists(OUTPUT_GEO):
        with open(OUTPUT_GEO, encoding="utf-8") as f:
            geo_cache = json.load(f)
        print(f"  Cache geocodage: {len(geo_cache):,} adresses")

    def make_addr(row):
        parts = [p for p in [row["no_voie"], row["type_voie"], row["voie"]] if p]
        addr  = " ".join(parts)
        if row["cp"] or row["commune"]:
            addr += f", {row['cp']} {row['commune']}"
        return addr.strip()

    df["address"]   = df.apply(make_addr, axis=1)
    unique_addrs    = df[df["address"].str.len() > 10]["address"].unique()
    to_geocode      = [a for a in unique_addrs if a not in geo_cache]

    print(f"  Adresses uniques: {len(unique_addrs):,}")
    print(f"  A geocoder: {len(to_geocode):,} (max {geo_max})")

    n_ok = n_err = 0
    for i, addr in enumerate(to_geocode[:geo_max]):
        result = geocode_ign(addr)
        geo_cache[addr] = list(result) if result else None
        if result:
            n_ok += 1
        else:
            n_err += 1
        time.sleep(GEO_DELAY)
        if (i + 1) % 100 == 0:
            with open(OUTPUT_GEO, "w", encoding="utf-8") as f:
                json.dump(geo_cache, f, ensure_ascii=False)
            print(f"  [{i+1}/{min(len(to_geocode), geo_max)}] OK={n_ok} ERR={n_err}",
                  flush=True)

    with open(OUTPUT_GEO, "w", encoding="utf-8") as f:
        json.dump(geo_cache, f, ensure_ascii=False)
    print(f"\n  Geocodage: {n_ok:,} OK, {n_err:,} echecs")
    print(f"  Cache total: {len(geo_cache):,}")

    # Appliquer geocoords au DataFrame
    df["lat"] = df["address"].apply(lambda a: geo_cache.get(a, [None, None])[0] if geo_cache.get(a) else None)
    df["lon"] = df["address"].apply(lambda a: geo_cache.get(a, [None, None])[1] if geo_cache.get(a) else None)
    n_geo = df["lat"].notna().sum()
    print(f"  Transactions geolocalisees: {n_geo:,} / {len(df):,} ({n_geo/len(df)*100:.0f}%)")

    # Filtre bbox: rejeter les geocodes hors vallee de Chamonix (dept 74 nord)
    GEO_LAT_MIN, GEO_LAT_MAX = 45.7, 46.3
    GEO_LON_MIN, GEO_LON_MAX = 6.2,  7.1
    bad_bbox = (
        df["lat"].notna() & (
            (df["lat"] < GEO_LAT_MIN) | (df["lat"] > GEO_LAT_MAX) |
            (df["lon"] < GEO_LON_MIN) | (df["lon"] > GEO_LON_MAX)
        )
    )
    n_bad_bbox = int(bad_bbox.sum())
    if n_bad_bbox > 0:
        df.loc[bad_bbox, ["lat", "lon"]] = None
        print(f"  Geocodes hors bbox [lat {GEO_LAT_MIN}-{GEO_LAT_MAX}, lon {GEO_LON_MIN}-{GEO_LON_MAX}] rejetes: {n_bad_bbox:,}")

    # ── 3b: Altimetrie OpenTopoData (batch 100 pts) ──────────────────────────
    alt_cache: dict = {}
    if os.path.exists(OUTPUT_ALT):
        with open(OUTPUT_ALT, encoding="utf-8") as f:
            alt_cache = json.load(f)
        print(f"\n  Cache altimetrie: {len(alt_cache):,} points")

    # Coordonnees uniques geocodees (arrondies a 4 decimales pour le cache)
    geo_rows     = df[df["lat"].notna() & df["lon"].notna()].copy()
    coords_round = geo_rows.apply(
        lambda r: (round(r["lat"], 4), round(r["lon"], 4)), axis=1
    )
    unique_coord_set = list(set(coords_round.tolist()))
    to_alti = [(la, lo) for la, lo in unique_coord_set
               if f"{la},{lo}" not in alt_cache]

    print(f"  Points alti uniques: {len(unique_coord_set):,} | a requeter: {len(to_alti):,}")
    print(f"  Batches de {ALT_BATCH}: ~{len(to_alti)//ALT_BATCH + 1} requetes "
          f"~{len(to_alti)//ALT_BATCH * ALT_DELAY:.0f}s")

    n_ok_a = n_err_a = 0
    for batch_start in range(0, len(to_alti), ALT_BATCH):
        batch = to_alti[batch_start : batch_start + ALT_BATCH]
        elevs = get_altitudes_batch(batch)
        for (la, lo), z in zip(batch, elevs):
            alt_cache[f"{la},{lo}"] = z
            if z is not None:
                n_ok_a += 1
            else:
                n_err_a += 1
        time.sleep(ALT_DELAY)  # 1 req/s rate limit
        if (batch_start // ALT_BATCH + 1) % 10 == 0:
            with open(OUTPUT_ALT, "w", encoding="utf-8") as f:
                json.dump(alt_cache, f, ensure_ascii=False)
            done = min(batch_start + ALT_BATCH, len(to_alti))
            print(f"  [{done}/{len(to_alti)}] OK={n_ok_a} ERR={n_err_a}", flush=True)

    with open(OUTPUT_ALT, "w", encoding="utf-8") as f:
        json.dump(alt_cache, f, ensure_ascii=False)
    print(f"  Altimetrie: {n_ok_a:,} OK, {n_err_a:,} echecs")

    # Appliquer altitude
    def get_alt_val(row):
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None
        key = f"{round(row['lat'],4)},{round(row['lon'],4)}"
        return alt_cache.get(key)

    df["altitude"] = df.apply(get_alt_val, axis=1)
    n_alt = df["altitude"].notna().sum()
    print(f"  Altitudes renseignees: {n_alt:,} / {len(df):,}")

    # Sanity altitude: vallee Chamonix 550-1800m, Plateau d'Assy 1500m — borne [300-2500m]
    bad_alt = df["altitude"].notna() & ((df["altitude"] < 300) | (df["altitude"] > 2500))
    n_bad_alt = int(bad_alt.sum())
    if n_bad_alt > 0:
        df.loc[bad_alt, ["lat", "lon", "altitude"]] = None
        print(f"  Altitudes hors plage [300-2500m] rejetees: {n_bad_alt:,} (mauvais geocodage)")

    # ── 3c: Distance au centre commune ───────────────────────────────────────
    def calc_dist(row):
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None
        center = COMMUNE_CENTERS.get(row["commune"])
        if not center:
            return None
        return round(haversine_km(row["lat"], row["lon"], center[0], center[1]), 3)

    df["dist_centre_km"] = df.apply(calc_dist, axis=1)
    n_dist = df["dist_centre_km"].notna().sum()
    print(f"  dist_centre_km: {n_dist:,} calcules")

    if n_dist > 0:
        print("\n  Statistiques dist_centre_km par commune:")
        for com, grp in df[df["dist_centre_km"].notna()].groupby("commune"):
            d = grp["dist_centre_km"]
            print(f"    {com}: med={d.median():.2f}km | max={d.max():.2f}km | n={len(d):,}")

    return df

# ── Phase 3d: Distance aux remontées mécaniques ──────────────────────────────

def add_ski_lift_distance(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule dist_ski_lift_km = distance haversine au lift le plus proche.
    Utilise le cache dvf/ski_lifts_osm.json (généré par fetch Overpass).
    N'ajoute la feature que si le fichier existe et que les transactions sont géocodées.
    """
    if not os.path.exists(OUTPUT_SKI):
        print("  ski_lifts_osm.json absent — skip distance remontees")
        return df

    with open(OUTPUT_SKI, encoding="utf-8") as f:
        raw_lifts = json.load(f)

    # Filtrer aux types utiles (exclure pylons, zip_line, goods…)
    lifts = [(l["lat"], l["lon"]) for l in raw_lifts
             if l.get("type") in SKI_LIFT_TYPES and l.get("lat") and l.get("lon")]

    if not lifts:
        print("  Aucun lift utile trouvé dans le cache — skip")
        return df

    lift_arr = np.array(lifts)  # shape (n_lifts, 2)
    print(f"\n  Distance remontées ({len(lifts)} stations/lifts utiles)...")

    def min_dist_lift(row):
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            return None
        lat, lon = float(row["lat"]), float(row["lon"])
        # Vectorisé haversine simplifié (cosine approx, ok pour distances <50km)
        dlat = np.radians(lift_arr[:, 0] - lat)
        dlon = np.radians(lift_arr[:, 1] - lon)
        a = np.sin(dlat/2)**2 + np.cos(np.radians(lat)) * np.cos(np.radians(lift_arr[:, 0])) * np.sin(dlon/2)**2
        dists = 6371.0 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return round(float(dists.min()), 3)

    df["dist_ski_lift_km"] = df.apply(min_dist_lift, axis=1)
    n_ok = df["dist_ski_lift_km"].notna().sum()
    med  = df["dist_ski_lift_km"].dropna().median()
    print(f"  dist_ski_lift_km: {n_ok:,} calculées | médiane={med:.2f}km")
    print(f"  Distribution: {df['dist_ski_lift_km'].dropna().quantile([0,.25,.5,.75,1]).round(2).to_dict()}")
    return df


# ── Phase 3e: Zone PLU (GPU Géoportail Urbanisme) ────────────────────────────

GPU_PLU_URL = "https://apicarto.ign.fr/api/gpu/zone-urba"
PLU_DELAY   = 0.12   # s entre requetes (rate limit genereux, ~8 req/s max)

# Encodage ordinal: U=3 (constructible) > AU=2 (futur) > A/Ah=1 (agricole) > N=0 (naturel)
# "HORS" = hors PLU (commune sans PLU digital) -> encoded comme A (droit limité)
PLU_TYPE_ENC = {
    "U":    3,   # zone urbaine constructible
    "AU":   2,   # zone à urbaniser
    "Ah":   1,   # agricole avec droits spéciaux
    "A":    1,   # agricole
    "N":    0,   # naturel / protégé
    "HORS": 1,   # hors zone PLU → droit commun limité
    "ERR":  None,
}


def query_plu_point(lat: float, lon: float) -> dict:
    """Requete GPU API pour un point. Retourne dict {typezone, libelle}."""
    geom = json.dumps({"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                      separators=(",", ":"))
    url  = f"{GPU_PLU_URL}?geom={urllib.parse.quote(geom)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "appart-alert-dvf/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        feats = data.get("features", [])
        if feats:
            p = feats[0]["properties"]
            return {"typezone": p.get("typezone", "HORS"), "libelle": p.get("libelle", "")}
        return {"typezone": "HORS", "libelle": ""}
    except Exception as e:
        return {"typezone": "ERR", "libelle": str(e)[:40]}


def add_plu_zones(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrichit chaque transaction géocodée avec sa zone PLU (GPU IGN).
    Cache dans dvf/dvf_plu_cache.json (clé = 'lat4,lon4').
    Ajoute colonnes: plu_typezone (str), plu_libelle (str), plu_enc (int 0-3).
    """
    print("\n  Phase 3e: Zones PLU (GPU IGN)...")

    plu_cache: dict = {}
    if os.path.exists(OUTPUT_PLU):
        with open(OUTPUT_PLU, encoding="utf-8") as f:
            plu_cache = json.load(f)
        print(f"  Cache PLU: {len(plu_cache):,} points")

    geo_df = df[df["lat"].notna() & df["lon"].notna()].copy()
    keys   = [f"{round(r['lat'],4)},{round(r['lon'],4)}"
              for _, r in geo_df.iterrows()]
    unique_keys = list(set(keys))
    to_query    = [k for k in unique_keys if k not in plu_cache
                   or plu_cache[k].get("typezone") == "ERR"]

    print(f"  Points uniques: {len(unique_keys):,} | à requêter: {len(to_query):,}")

    n_ok = n_hors = n_err = 0
    for i, key in enumerate(to_query):
        la, lo = map(float, key.split(","))
        result = query_plu_point(la, lo)
        plu_cache[key] = result
        tz = result["typezone"]
        if tz == "ERR":     n_err  += 1
        elif tz == "HORS":  n_hors += 1
        else:               n_ok   += 1
        time.sleep(PLU_DELAY)
        if (i + 1) % 200 == 0:
            with open(OUTPUT_PLU, "w", encoding="utf-8") as f:
                json.dump(plu_cache, f, ensure_ascii=False)
            print(f"  [{i+1}/{len(to_query)}] ok={n_ok} hors={n_hors} err={n_err}",
                  flush=True)

    with open(OUTPUT_PLU, "w", encoding="utf-8") as f:
        json.dump(plu_cache, f, ensure_ascii=False)

    if to_query:
        print(f"  Requêtes PLU: {n_ok} OK | {n_hors} hors-PLU | {n_err} erreurs")

    # Appliquer au DataFrame
    row_keys = [f"{round(r['lat'],4)},{round(r['lon'],4)}"
                if pd.notna(r.get("lat")) else None
                for _, r in df.iterrows()]

    def get_tz(key):
        if key is None:
            return "HORS", ""
        v = plu_cache.get(key, {})
        return v.get("typezone", "HORS"), v.get("libelle", "")

    df["plu_typezone"] = [get_tz(k)[0] for k in row_keys]
    df["plu_libelle"]  = [get_tz(k)[1] for k in row_keys]
    df["plu_enc"]      = df["plu_typezone"].map(
        lambda tz: PLU_TYPE_ENC.get(tz, PLU_TYPE_ENC.get(tz.rstrip("0123456789"), 1))
    ).fillna(1).astype(int)

    # Stats
    dist = df["plu_typezone"].value_counts()
    print(f"  Distribution zones: {dict(dist.head(8))}")
    print(f"  plu_enc moyen par type_local:")
    for typ in ["appart", "maison"]:
        sub = df[df["type_local"] == typ]
        print(f"    {typ}: {sub['plu_enc'].mean():.2f}  zones={dict(sub['plu_typezone'].value_counts().head(4))}")

    return df


# ── Phase 4: Export ───────────────────────────────────────────────────────────

def export_clean(df: pd.DataFrame):
    cols = [
        "date", "annee", "mois", "commune", "section", "no_plan",
        "no_voie", "type_voie", "voie", "cp",
        "valeur", "surface", "pieces", "type_local", "code_type",
        "prix_m2", "has_parking", "n_dependances", "nb_lots", "surf_terrain", "surf_carrez",
        "plu_typezone", "plu_libelle", "plu_enc",
    ]
    # garder uniquement les colonnes qui existent
    cols = [c for c in cols if c in df.columns]
    for opt in ["lat", "lon", "altitude", "dist_centre_km", "dist_ski_lift_km"]:
        if opt in df.columns:
            cols.append(opt)
    df[cols].to_csv(OUTPUT_CLEAN, index=False, encoding="utf-8")
    print(f"\n  Exporte: {OUTPUT_CLEAN} ({len(df):,} lignes)")

def export_stats(stats: dict):
    with open(OUTPUT_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  Export: {OUTPUT_STATS}")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pipeline DVF dept 74")
    parser.add_argument("--geo", action="store_true",
                        help="Activer geocodage + altimetrie IGN")
    parser.add_argument("--geo-max", type=int, default=GEO_MAX_NEW,
                        help=f"Max adresses a geocoder (defaut: {GEO_MAX_NEW})")
    args = parser.parse_args()

    t0 = time.time()

    df    = load_dvf()
    stats = compute_stats(df)

    if args.geo:
        df = run_geocoding(df, geo_max=args.geo_max)
        df = add_ski_lift_distance(df)
        df = add_plu_zones(df)

    print("\n" + "=" * 60)
    print("Phase 4: Export")
    print("=" * 60)
    export_clean(df)
    export_stats(stats)

    elapsed = time.time() - t0
    geo_cols = [c for c in ["lat","lon","altitude","dist_centre_km"] if c in df.columns]
    has_pk   = int(df["has_parking"].sum()) if "has_parking" in df.columns else 0

    print(f"\nOK Pipeline termine en {elapsed:.1f}s")
    print(f"  {len(df):,} transactions | {len(stats['communes'])} communes")
    print(f"  has_parking=1: {has_pk:,} ({has_pk/len(df)*100:.0f}%)")
    if geo_cols:
        n_geo = df["lat"].notna().sum() if "lat" in df.columns else 0
        print(f"  Colonnes geo: {geo_cols} | geocodees: {n_geo:,}")
    print(f"  Stats: {OUTPUT_STATS}")
    print(f"  Donnees: {OUTPUT_CLEAN}")
