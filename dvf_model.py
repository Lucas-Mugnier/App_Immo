#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dvf_model.py -- Modeles hedoniques XGBoost separes appart / maison
Appart (n~5100): log_surface, pieces, commune, section, annee,
                 n_dependances, nb_lots, [lat, lon, altitude, dist]
Maison (n~1600): idem + log_surf_terrain
Global (fallback): tous types ensemble

Produit:
  dvf/dvf_model_appart.pkl  -- modele appart (R2~0.73)
  dvf/dvf_model_maison.pkl  -- modele maison (R2~0.57)
  dvf/dvf_model.pkl         -- modele global (fallback, R2~0.70)
  dvf/dvf_model_meta.json   -- performances, importances, grille de prix
  dvf/dvf_stats.json        -- mis a jour avec champ 'model'

Usage: C:/Users/lucas/anaconda3/python.exe dvf_model.py
"""

import json
import os
import sys
import pickle
import warnings
warnings.filterwarnings("ignore")

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("pandas/numpy manquant.")
    sys.exit(1)

try:
    from sklearn.model_selection import KFold, cross_val_score
    from sklearn.preprocessing import LabelEncoder
    from sklearn.metrics import r2_score, mean_absolute_error
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    import xgboost as xgb
    HAS_XGB = True
except ImportError as e:
    print(f"WARN: {e}. Fallback sur Ridge.")
    HAS_XGB = False

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DVF_DIR      = os.path.join(BASE_DIR, "dvf")
INPUT_CLEAN  = os.path.join(DVF_DIR, "dvf_clean.csv")
INPUT_STATS  = os.path.join(DVF_DIR, "dvf_stats.json")
OUTPUT_MODEL        = os.path.join(DVF_DIR, "dvf_model.pkl")
OUTPUT_MODEL_APPART = os.path.join(DVF_DIR, "dvf_model_appart.pkl")
OUTPUT_MODEL_MAISON = os.path.join(DVF_DIR, "dvf_model_maison.pkl")
OUTPUT_META  = os.path.join(DVF_DIR, "dvf_model_meta.json")

COMMUNE_CENTERS = {
    "CHAMONIX MONT BLANC":     (45.9237, 6.8694),
    "DOMANCY":                 (45.8928, 6.6867),
    "LES HOUCHES":             (45.8999, 6.8037),
    "PASSY":                   (45.9178, 6.6949),
    "SALLANCHES":              (45.9386, 6.6346),
    "SERVOZ":                  (45.9334, 6.7792),
    "SAINT GERVAIS LES BAINS": (45.8925, 6.7028),
}

# ── Chargement + prep ─────────────────────────────────────────────────────────

def load_data():
    print("Chargement dvf_clean.csv...")
    df = pd.read_csv(INPUT_CLEAN, low_memory=False)
    print(f"  {len(df):,} transactions")

    geo_cols = [c for c in ["lat","lon","altitude","dist_centre_km"] if c in df.columns]
    if geo_cols:
        n_geo = df["lat"].notna().sum() if "lat" in df.columns else 0
        print(f"  Geo: {n_geo:,}/{len(df):,} geocodees")

    n_ap = (df["type_local"]=="appart").sum()
    n_ma = (df["type_local"]=="maison").sum()
    print(f"  Appartements: {n_ap:,}  |  Maisons: {n_ma:,}")

    if "has_parking" in df.columns:
        pk = int(df["has_parking"].sum())
        print(f"  has_parking=1: {pk:,} ({pk/len(df)*100:.0f}%)")
    else:
        df["has_parking"] = 0

    if "n_dependances" in df.columns:
        df["n_dependances"] = pd.to_numeric(df["n_dependances"], errors="coerce").fillna(0).clip(0,5).astype(int)
    else:
        df["n_dependances"] = df["has_parking"].fillna(0).astype(int)

    if "nb_lots" in df.columns:
        df["nb_lots"] = pd.to_numeric(df["nb_lots"], errors="coerce").fillna(0).clip(0,8).astype(int)
    else:
        df["nb_lots"] = 0

    # surf_carrez -> carrez_ratio (apparts seulement)
    # NB: on N'utilise PAS surf_carrez comme surface principale (30% sans donnée = incohérence)
    # On utilise le ratio carrez/surface comme feature qualitative
    if "surf_carrez" in df.columns:
        df["surf_carrez"] = pd.to_numeric(df["surf_carrez"], errors="coerce")
        # carrez_ratio: proportion de l'espace Carrez-mesuré (habitable) vs surface totale
        # Imputation: 1.0 pour les apparts sans Carrez (neutre)
        # Pour les maisons: NaN → 1.0 (Carrez ne s'applique pas)
        df["carrez_ratio"] = (df["surf_carrez"] / df["surface"]).clip(0.1, 1.05).fillna(1.0)
        n_carrez = int(df["surf_carrez"].notna().sum())
        print(f"  surf_carrez renseigne: {n_carrez:,} ({n_carrez/len(df)*100:.0f}%)")
    else:
        df["carrez_ratio"] = 1.0

    # dist_ski_lift_km -> ski_c
    if "dist_ski_lift_km" in df.columns:
        df["dist_ski_lift_km"] = pd.to_numeric(df["dist_ski_lift_km"], errors="coerce")
        # Imputation par médiane commune
        for commune in df["commune"].unique():
            med = df.loc[(df["commune"]==commune) & df["dist_ski_lift_km"].notna(), "dist_ski_lift_km"].median()
            mask = (df["commune"] == commune) & df["dist_ski_lift_km"].isna()
            df.loc[mask, "dist_ski_lift_km"] = med if pd.notna(med) else 3.0
    else:
        df["dist_ski_lift_km"] = 3.0

    # surf_terrain -> log_surf_terrain
    if "surf_terrain" in df.columns:
        df["surf_terrain"] = pd.to_numeric(df["surf_terrain"], errors="coerce")
        df.loc[df["surf_terrain"] > 50000, "surf_terrain"] = None
        for commune in df["commune"].unique():
            mask_maison = (df["commune"] == commune) & (df["type_local"] == "maison")
            med_st = df.loc[mask_maison & df["surf_terrain"].notna(), "surf_terrain"].median()
            if pd.notna(med_st):
                df.loc[mask_maison & df["surf_terrain"].isna(), "surf_terrain"] = med_st
        df["surf_terrain"] = df["surf_terrain"].fillna(1.0).clip(1.0)
        df["log_surf_terrain"] = np.log(df["surf_terrain"])
        n_st = int((df["surf_terrain"] > 1.5).sum())
        print(f"  surf_terrain renseigne: {n_st:,} ({n_st/len(df)*100:.0f}%)")
    else:
        df["log_surf_terrain"] = 0.0

    # has_terrain: binaire (remplace type_enc de facon interpretable)
    df["has_terrain"] = (df["surf_terrain"] > 10).astype(float) if "surf_terrain" in df.columns else 0.0

    # terrain_u_m2 / terrain_n_m2: interaction terrain × PLU
    # Terrain constructible (zone U) vaut 800-1500€/m2 a Chamonix
    # Terrain non-constructible (zone N/A) vaut 5-50€/m2
    # XGBoost peut apprendre l'interaction mais l'encoder explicitement aide le modele maison
    if "surf_terrain" in df.columns and "plu_enc" in df.columns:
        plu = pd.to_numeric(df["plu_enc"], errors="coerce").fillna(2.0)
        st  = pd.to_numeric(df["surf_terrain"], errors="coerce").fillna(1.0).clip(1.0)
        df["terrain_u_m2"] = np.where(plu >= 2.5, st, 0.0)   # zone U (plu_enc=3)
        df["terrain_n_m2"] = np.where(plu < 1.5,  st, 0.0)   # zones N/A (plu_enc=0-1)
        df["log_terrain_u"] = np.log(df["terrain_u_m2"].clip(1.0))
        df["log_terrain_n"] = np.log(df["terrain_n_m2"].clip(1.0))
        n_u = int((df["terrain_u_m2"] > 10).sum())
        n_n = int((df["terrain_n_m2"] > 10).sum())
        print(f"  terrain_u>10m2: {n_u:,}  terrain_n>10m2: {n_n:,}")
    else:
        df["terrain_u_m2"] = 0.0; df["terrain_n_m2"] = 0.0
        df["log_terrain_u"] = 0.0; df["log_terrain_n"] = 0.0

    # voie: conserver pour target-encoding (lieu-dit/hameau)
    if "voie" in df.columns:
        df["voie"] = df["voie"].fillna("INCONNUE").str.strip().str.upper()
    else:
        df["voie"] = "INCONNUE"

    # pieces_per_100m2: densite de pieces = proxy qualite
    # petit chalet 3p/70m2 vs grande vieille ferme 10p/300m2 meme prix total
    df["pieces_per_100m2"] = (df["pieces"] / (df["surface"] / 100.0)).fillna(2.0).clip(0.2, 10.0)

    # plu_enc: zone PLU (U=3, AU=2, Ah=1, A=1, N=0, HORS=1, ERR->NaN)
    # Cle pour maisons: terrain zone UA/UC >> zone N/A
    if "plu_enc" in df.columns:
        df["plu_enc"] = pd.to_numeric(df["plu_enc"], errors="coerce")
        n_plu = int(df["plu_enc"].notna().sum())
        print(f"  plu_enc renseigne: {n_plu:,} ({n_plu/len(df)*100:.0f}%)")
        # Imputation par mediane commune x type_local
        for (com, typ), grp in df.groupby(["commune", "type_local"]):
            med = grp["plu_enc"].median()
            mask = df["commune"].eq(com) & df["type_local"].eq(typ) & df["plu_enc"].isna()
            df.loc[mask, "plu_enc"] = med if pd.notna(med) else 2.0
        df["plu_enc"] = df["plu_enc"].fillna(2.0)
    else:
        df["plu_enc"] = 2.0  # U par defaut

    # Imputer pieces
    df["pieces"] = pd.to_numeric(df["pieces"], errors="coerce")
    for (com, typ), grp in df.groupby(["commune", "type_local"]):
        med  = grp["pieces"].median()
        mask = df["commune"].eq(com) & df["type_local"].eq(typ) & df["pieces"].isna()
        df.loc[mask, "pieces"] = med if not np.isnan(med) else 2.0
    df["pieces"] = df["pieces"].fillna(2.0).clip(1, 15)

    df["log_surface"] = np.log(df["surface"])
    df["log_prix_m2"] = np.log(df["prix_m2"])
    df["section"]     = df["section"].fillna("?")

    return df

# ── Imputation geo ────────────────────────────────────────────────────────────

def impute_geo(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "dist_centre_km" in df.columns:
        bad = df["dist_centre_km"] > 20
        n_bad = int(bad.sum())
        if n_bad > 0:
            print(f"  Geocodages suspects (dist>20km): {n_bad:,}")
            df.loc[bad, ["lat","lon","altitude","dist_centre_km"]] = None
            if "_was_geocoded" in df.columns:
                df.loc[bad, "_was_geocoded"] = False
    if "lat" in df.columns:
        for commune, (clat, clon) in COMMUNE_CENTERS.items():
            mask = (df["commune"] == commune) & df["lat"].isna()
            df.loc[mask, "lat"] = clat
            df.loc[mask, "lon"] = clon
    if "altitude" in df.columns:
        for commune in df["commune"].unique():
            med = df.loc[(df["commune"]==commune) & df["altitude"].notna(), "altitude"].median()
            mask = (df["commune"] == commune) & df["altitude"].isna()
            df.loc[mask, "altitude"] = med if pd.notna(med) else 900.0
    if "dist_centre_km" in df.columns:
        for commune in df["commune"].unique():
            med = df.loc[(df["commune"]==commune) & df["dist_centre_km"].notna(), "dist_centre_km"].median()
            mask = (df["commune"] == commune) & df["dist_centre_km"].isna()
            df.loc[mask, "dist_centre_km"] = med if pd.notna(med) else 1.0
    return df

# ── Feature engineering ───────────────────────────────────────────────────────

def build_features(df: pd.DataFrame, use_geo: bool = True,
                   le_commune=None, le_section=None, fit=True,
                   voie_enc_dict=None):
    """
    Construit X, y. Encodeurs passes en parametre pour reutilisation
    entre modeles appart/maison (memes communes, memes sections).
    NB: pas de type_enc — modelise par has_terrain (binaire physique).

    voie_enc_dict: dict {voie -> float} pour target-encoding voie/lieu-dit
                   Si fit=True, calcule et retourne dans le dict.
                   Si fit=False, applique le dict (lookup + fallback commune).
    """
    df = df.copy()

    if fit:
        le_commune = LabelEncoder(); le_section = LabelEncoder()
        df["commune_enc"] = le_commune.fit_transform(df["commune"])
        df["section_enc"] = le_section.fit_transform(df["section"])
    else:
        df["commune_enc"] = le_commune.transform(df["commune"])
        df["section_enc"] = le_section.transform(df["section"])

    # Preparer colonnes numeriques
    for col in ["n_dependances","nb_lots","log_surf_terrain","has_terrain","carrez_ratio","dist_ski_lift_km","plu_enc","pieces_per_100m2"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    feature_cols = [
        "log_surface",
        "pieces",
        "commune_enc",
        "section_enc",
        "annee",
        "n_dependances",
        "nb_lots",
    ]

    # carrez_ratio: apparts principalement (70% coverage). Pour maisons = 1.0 (impute, neutre).
    # On l'ajoute seulement si variance suffisante (sinon = tous 1.0 = inutile)
    if "carrez_ratio" in df.columns and df["carrez_ratio"].std() > 0.01:
        feature_cols.append("carrez_ratio")

    # has_terrain: utile dans le modele global (distingue maison/appart)
    # pas utile dans un modele appart-only ou maison-only
    if "has_terrain" in df.columns and df["has_terrain"].std() > 0.01:
        feature_cols.append("has_terrain")

    # log_surf_terrain: remplace par log_terrain_u + log_terrain_n (interaction PLU x terrain)
    # - log_terrain_u: terrain constructible (zone U) -> valeur elevee par m2
    # - log_terrain_n: terrain non-constructible (zone N/A) -> valeur faible par m2
    # Ces deux features encodent l'interaction explicitement sans attendre XGBoost
    for tcol in ["log_terrain_u", "log_terrain_n"]:
        if tcol in df.columns and (pd.to_numeric(df[tcol], errors="coerce") > 0.1).mean() > 0.03:
            feature_cols.append(tcol)
    # log_surf_terrain en fallback si pas de PLU
    if "log_terrain_u" not in feature_cols and "log_terrain_n" not in feature_cols:
        if "log_surf_terrain" in df.columns and (df["log_surf_terrain"] > 0.1).mean() > 0.05:
            feature_cols.append("log_surf_terrain")

    # plu_enc: zone PLU (U=3 -> N=0)
    # Maisons: variance forte (zone N/A = terrain quasi sans valeur vs zone U = constructible)
    # Apparts: quasi tous zone U (std~0.2) -> faiblement informatif mais on l'ajoute quand meme
    if "plu_enc" in df.columns and df["plu_enc"].std() > 0.05:
        feature_cols.append("plu_enc")

    # pieces_per_100m2: densite de pieces (proxy qualite/epoque)
    # petit chalet moderne 3p/70m2=4.3 vs vieille ferme 10p/300m2=3.3 — distingue subtil mais reel
    if "pieces_per_100m2" in df.columns and df["pieces_per_100m2"].std() > 0.1:
        feature_cols.append("pieces_per_100m2")

    # voie_te: target-encoding du lieu-dit/hameau (Bettex, Les Praz, Argentiere...)
    # Forte correlation r~0.57 avec log_pm2 — encode micro-quartier intra-commune
    # Smoothing k=10 pour eviter overfitting sur voies rares (<5 transactions)
    if "voie" in df.columns:
        y_col = "log_prix_m2"
        global_mean = df[y_col].mean() if y_col in df.columns else 9.0
        K_SMOOTH = 10  # smoothing factor: voie avec peu de transactions -> tire vers la moyenne
        if voie_enc_dict is None:
            # Calcul depuis les donnees passees (fit ou non: on encode depuis le sous-ensemble)
            voie_stats = df.groupby("voie")[y_col].agg(["mean", "count"])
            voie_enc_dict = {}
            for voie, row in voie_stats.iterrows():
                voie_enc_dict[voie] = (row["mean"] * row["count"] + global_mean * K_SMOOTH) / (row["count"] + K_SMOOTH)
            # Fallback par commune si voie inconnue au scoring
            commune_means = df.groupby("commune")[y_col].mean().to_dict()
            voie_enc_dict["__commune_means__"] = commune_means
            voie_enc_dict["__global_mean__"]   = float(global_mean)
        # Appliquer l'encodage
        if voie_enc_dict is not None:
            commune_means = voie_enc_dict.get("__commune_means__", {})
            gm = voie_enc_dict.get("__global_mean__", global_mean)
            def encode_voie(row):
                v = row.get("voie", "INCONNUE") if hasattr(row, "get") else "INCONNUE"
                if v in voie_enc_dict:
                    return voie_enc_dict[v]
                # fallback: commune mean
                com = row.get("commune", "") if hasattr(row, "get") else ""
                return commune_means.get(com, gm)
            df["voie_te"] = df.apply(encode_voie, axis=1)
            feature_cols.append("voie_te")

    # Features geo
    if use_geo:
        for col, alias in [("lat","lat_c"),("lon","lon_c"),
                           ("altitude","altitude_c"),("dist_centre_km","dist_c")]:
            if col in df.columns:
                n_real = df[col].notna().sum()
                if n_real >= 100:
                    df[alias] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                    feature_cols.append(alias)

        # Distance aux remontées (utile en contexte ski resort)
        if "dist_ski_lift_km" in df.columns and df["dist_ski_lift_km"].notna().sum() >= 100:
            df["ski_c"] = df["dist_ski_lift_km"].astype(float)
            feature_cols.append("ski_c")

    X = df[feature_cols].values.astype(float)
    y = df["log_prix_m2"].values
    return X, y, feature_cols, le_commune, le_section, df, voie_enc_dict

# ── Modele XGBoost ────────────────────────────────────────────────────────────

def make_model():
    if HAS_XGB:
        return xgb.XGBRegressor(
            n_estimators=600, max_depth=6, learning_rate=0.04,
            subsample=0.8, colsample_bytree=0.75, min_child_weight=3,
            gamma=0.05, reg_alpha=0.1, reg_lambda=1.0,
            random_state=42, n_jobs=-1, verbosity=0,
        )
    return Pipeline([("scaler", StandardScaler()), ("ridge", Ridge(alpha=10.0))])

def train_model(X, y, feature_cols, label=""):
    tag = f" [{label}]" if label else ""
    print(f"\nEntrainement XGBoost{tag}...")
    print(f"  n={len(X):,} | {len(feature_cols)} features: {feature_cols}")
    model = make_model()
    kf    = KFold(n_splits=5, shuffle=True, random_state=42)
    cv_r2 = cross_val_score(model, X, y, cv=kf, scoring="r2", n_jobs=-1)
    cv_mae= cross_val_score(model, X, y, cv=kf,
                            scoring="neg_mean_absolute_error", n_jobs=-1)
    print(f"  CV R2 : {cv_r2.mean():.3f} +/- {cv_r2.std():.3f}")
    model.fit(X, y)
    y_pred  = model.predict(X)
    mae_eur = float(np.mean(np.abs(np.exp(y_pred) - np.exp(y))))
    r2_full = float(r2_score(y, y_pred))
    print(f"  R2 train: {r2_full:.3f}  |  MAE train: {mae_eur:,.0f} e/m2")
    return model, {
        "cv_r2_mean": round(float(cv_r2.mean()), 4),
        "cv_r2_std":  round(float(cv_r2.std()),  4),
        "mae_eur":    round(mae_eur, 1),
        "r2_train":   round(r2_full, 4),
        "n_samples":  int(len(X)),
        "features":   feature_cols,
    }

def get_importances(model, feature_cols):
    if HAS_XGB and hasattr(model, "feature_importances_"):
        imps = model.feature_importances_
        return dict(sorted(
            {f: round(float(v), 4) for f,v in zip(feature_cols, imps)}.items(),
            key=lambda x: -x[1]
        ))
    return {}

# ── Grille de prix (appart-centric) ──────────────────────────────────────────

def build_price_grid(model, df_enc, le_commune, le_section, feature_cols, typ="appart"):
    import datetime
    current_year = datetime.datetime.now().year
    results = {}
    for commune in sorted(df_enc["commune"].unique()):
        dfc = df_enc[df_enc["commune"] == commune]
        top_section = dfc["section"].mode().iloc[0] if not dfc["section"].empty else "A"
        try:
            comm_enc = float(le_commune.transform([commune])[0])
            sect_enc = float(le_section.transform([top_section])[0])
        except ValueError:
            continue
        lat_med  = float(dfc["lat_c"].median())       if "lat_c"      in dfc.columns else 0.0
        lon_med  = float(dfc["lon_c"].median())       if "lon_c"      in dfc.columns else 0.0
        alt_med  = float(dfc["altitude_c"].median())  if "altitude_c" in dfc.columns else 0.0

        surfaces = [20,  30,  40,  50,  60,  70,  80,  100, 120]
        pieces   = [1,   1,   2,   2,   3,   3,   4,   4,   5  ]
        grid_rows = []
        for s, p in zip(surfaces, pieces):
            base_vals = {
                "log_surface":      np.log(s),
                "pieces":           float(p),
                "commune_enc":      comm_enc,
                "section_enc":      sect_enc,
                "annee":            float(current_year),
                "n_dependances":    0.0,
                "nb_lots":          1.0,
                "has_terrain":      1.0 if typ == "maison" else 0.0,
                "log_surf_terrain": np.log(500) if typ == "maison" else 0.0,
                "lat_c":            lat_med,
                "lon_c":            lon_med,
                "altitude_c":       alt_med,
                "dist_c":           0.0,
            }
            row_base  = [base_vals.get(f, 0.0) for f in feature_cols]
            pred_no_pk = int(round(float(np.exp(model.predict([row_base])[0]))))

            pk_vals = dict(base_vals)
            pk_vals["n_dependances"] = 1.0; pk_vals["nb_lots"] = 2.0
            row_pk = [pk_vals.get(f, 0.0) for f in feature_cols]
            pred_pk = int(round(float(np.exp(model.predict([row_pk])[0]))))

            grid_rows.append({
                "surface":           s,
                "pieces":            p,
                "prix_m2_estime":    pred_no_pk,
                "prix_m2_avec_pk":   pred_pk,
                "prix_total_estime": int(round(s * pred_no_pk / 1000)) * 1000,
            })
        results[commune] = grid_rows
    return results

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("DVF Model -- Hedonique XGBoost APPART + MAISON")
    print("=" * 60)

    # 1. Chargement
    df = load_data()
    df["_was_geocoded"] = (
        df["lat"].notna() & df["lon"].notna()
        if "lat" in df.columns else pd.Series(False, index=df.index)
    )
    df = impute_geo(df)

    # ── Encodeurs partages (memes communes + sections dans les deux sous-modeles) ──
    le_commune_global = LabelEncoder().fit(df["commune"])
    le_section_global = LabelEncoder().fit(df["section"])

    # ── 2. MODELE APPART ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("MODELE APPARTEMENTS")
    print("=" * 60)
    df_ap = df[df["type_local"] == "appart"].copy()
    # Pour les apparts: log_surf_terrain=0 partout -> feature inutile, retirer
    # has_terrain=0 partout -> inutile aussi
    X_ap, y_ap, fcols_ap, le_c_ap, le_s_ap, df_ap_enc, voie_enc_ap = build_features(
        df_ap, use_geo=True,
        le_commune=le_commune_global, le_section=le_section_global, fit=False
    )
    model_ap, perf_ap = train_model(X_ap, y_ap, fcols_ap, label="APPART")
    imps_ap = get_importances(model_ap, fcols_ap)
    if imps_ap:
        print("Importances (appart):")
        for f,v in list(imps_ap.items())[:8]:
            print(f"  {f:<22} {'#'*int(v*35)} {v:.4f}")
    with open(OUTPUT_MODEL_APPART, "wb") as f:
        pickle.dump({"model": model_ap, "le_commune": le_commune_global,
                     "le_section": le_section_global, "features": fcols_ap,
                     "voie_enc": voie_enc_ap, "type": "appart"}, f)
    print(f"Modele appart sauvegarde: {OUTPUT_MODEL_APPART}")

    # ── 3. MODELE MAISON ──────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("MODELE MAISONS")
    print("=" * 60)
    df_ma = df[df["type_local"] == "maison"].copy()
    X_ma, y_ma, fcols_ma, le_c_ma, le_s_ma, df_ma_enc, voie_enc_ma = build_features(
        df_ma, use_geo=True,
        le_commune=le_commune_global, le_section=le_section_global, fit=False
    )
    model_ma, perf_ma = train_model(X_ma, y_ma, fcols_ma, label="MAISON")
    imps_ma = get_importances(model_ma, fcols_ma)
    if imps_ma:
        print("Importances (maison):")
        for f,v in list(imps_ma.items())[:8]:
            print(f"  {f:<22} {'#'*int(v*35)} {v:.4f}")
    with open(OUTPUT_MODEL_MAISON, "wb") as f:
        pickle.dump({"model": model_ma, "le_commune": le_commune_global,
                     "le_section": le_section_global, "features": fcols_ma,
                     "voie_enc": voie_enc_ma, "type": "maison"}, f)
    print(f"Modele maison sauvegarde: {OUTPUT_MODEL_MAISON}")

    # ── 4. MODELE GLOBAL (fallback / comparaison) ─────────────────────────────
    print("\n" + "=" * 60)
    print("MODELE GLOBAL (fallback)")
    print("=" * 60)
    X_gl, y_gl, fcols_gl, le_c_gl, le_s_gl, df_enc, voie_enc_gl = build_features(
        df, use_geo=True,
        le_commune=le_commune_global, le_section=le_section_global, fit=False
    )
    model_gl, perf_gl = train_model(X_gl, y_gl, fcols_gl, label="GLOBAL")
    imps_gl = get_importances(model_gl, fcols_gl)
    with open(OUTPUT_MODEL, "wb") as f:
        pickle.dump({"model": model_gl, "le_commune": le_commune_global,
                     "le_section": le_section_global, "features": fcols_gl,
                     "voie_enc": voie_enc_gl,
                     "model_appart": model_ap, "features_appart": fcols_ap,
                     "voie_enc_appart": voie_enc_ap,
                     "model_maison": model_ma, "features_maison": fcols_ma,
                     "voie_enc_maison": voie_enc_ma,
                     "type": "global"}, f)
    print(f"Modele global sauvegarde: {OUTPUT_MODEL}")

    # ── 5. Grille de prix (appart, dashboard) ─────────────────────────────────
    print("\nCalcul grille de prix (appart)...")
    price_grid = build_price_grid(model_ap, df_ap_enc,
                                  le_commune_global, le_section_global,
                                  fcols_ap, typ="appart")

    # ── 6. Meta JSON ──────────────────────────────────────────────────────────
    meta = {
        "perf_appart":  perf_ap,
        "perf_maison":  perf_ma,
        "perf_global":  perf_gl,
        "importances_appart": imps_ap,
        "importances_maison": imps_ma,
        "importances_global": imps_gl,
        "price_grid":   price_grid,
        "model_type":   "XGBoost" if HAS_XGB else "Ridge",
        "geo_features": [c for c in ["lat_c","lon_c","altitude_c","dist_c"]
                         if c in fcols_ap],
    }
    with open(OUTPUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"Meta: {OUTPUT_META}")

    # ── 7. MAJ dvf_stats.json ─────────────────────────────────────────────────
    if os.path.exists(INPUT_STATS):
        with open(INPUT_STATS, encoding="utf-8") as f:
            stats = json.load(f)
        stats["model"] = {
            "r2_cv":          perf_ap["cv_r2_mean"],     # appart = reference
            "r2_cv_appart":   perf_ap["cv_r2_mean"],
            "r2_cv_maison":   perf_ma["cv_r2_mean"],
            "r2_cv_global":   perf_gl["cv_r2_mean"],
            "r2_cv_base":     perf_gl["cv_r2_mean"],     # compat ancienne cle
            "mae_eur":        perf_ap["mae_eur"],
            "mae_eur_maison": perf_ma["mae_eur"],
            "model_type":     meta["model_type"],
            "geo_features":   meta["geo_features"],
            "top_features":   list(imps_ap.keys())[:5] if imps_ap else [],
            "n_samples":      perf_ap["n_samples"],
            "n_maisons":      perf_ma["n_samples"],
        }
        with open(INPUT_STATS, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        print("dvf_stats.json mis a jour")

    # ── 8. Resume ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"APPART  R2 CV={perf_ap['cv_r2_mean']:.3f}  MAE={perf_ap['mae_eur']:,.0f} e/m2"
          f"  n={perf_ap['n_samples']:,}")
    print(f"MAISON  R2 CV={perf_ma['cv_r2_mean']:.3f}  MAE={perf_ma['mae_eur']:,.0f} e/m2"
          f"  n={perf_ma['n_samples']:,}")
    print(f"GLOBAL  R2 CV={perf_gl['cv_r2_mean']:.3f}  MAE={perf_gl['mae_eur']:,.0f} e/m2"
          f"  n={perf_gl['n_samples']:,}")
    print(f"Features appart: {fcols_ap}")
    print("=" * 60)
