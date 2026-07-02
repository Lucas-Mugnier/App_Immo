"""
build_avm_appart.py
====================
AVM appartements Chamonix + vallée Mont-Blanc
- Nettoyage outliers (prix/m² hors marché, caves/parkings)
- XGBoost log(valeur) → MAPE honnête par k-fold CV
- Index inflation annuel
- Export JSON pour dashboard JS
- Export pkl pour predict_avm.py

Features uniquement bâti (pas de terrain) → modèle fiable
"""

import pandas as pd
import numpy as np
import pickle, json
from pathlib import Path
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor

# ── Chemins ────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
DVF  = BASE / "dvf"
OUT  = BASE / "dvf"

# ── 1. Chargement ─────────────────────────────────────────────────────
print("=== 1. Chargement DVF ===")
df = pd.read_csv(DVF / "dvf_clean.csv")
apt = df[df["type_local"] == "appart"].copy()
print(f"Apparts bruts : {len(apt)}")
print(f"Communes : {apt['commune'].value_counts().to_dict()}")

# ── 2. Nettoyage ───────────────────────────────────────────────────────
print("\n=== 2. Nettoyage ===")

# Seuils prix/m²
PM2_MIN = 3_500   # en dessous = cave/parking bundles, HLM, erreurs
PM2_MAX = 30_000  # au dessus  = erreur DVF ou ultra-luxury outlier

# Surface minimum (cave = <12m²)
SURF_MIN = 14

before = len(apt)
apt = apt[
    (apt["prix_m2"] >= PM2_MIN) &
    (apt["prix_m2"] <= PM2_MAX) &
    (apt["surface"] >= SURF_MIN) &
    (apt["surf_terrain"].fillna(0) == 0) &   # exclure apparts avec terrain (maisons mal codees)
    apt["valeur"].notna() &
    apt["surface"].notna()
].copy()

print(f"Après nettoyage : {len(apt)} (supprimé {before-len(apt)})")
print(f"Par commune :")
print(apt.groupby("commune")["prix_m2"].agg(["count","median"]).round(0))

# ── 3. Feature engineering ────────────────────────────────────────────
print("\n=== 3. Features ===")

# Encodage label
le_com = LabelEncoder()
le_sec = LabelEncoder()
apt["commune_enc"] = le_com.fit_transform(apt["commune"].fillna("CHAMONIX MONT BLANC"))
apt["section_enc"] = le_sec.fit_transform(apt["section"].fillna("G"))

# Log surface
apt["log_surface"] = np.log(apt["surface"].clip(1))

# Pièces
apt["pieces_f"] = apt["pieces"].fillna(apt["pieces"].median()).clip(1, 10)

# Dépendances (caves, parkings)
apt["n_dep_f"] = apt["n_dependances"].clip(0, 5).astype(float)

# Géo
med = {
    "lat":  apt["lat"].dropna().median(),
    "lon":  apt["lon"].dropna().median(),
    "alt":  apt["altitude"].dropna().median(),
    "dist": apt["dist_centre_km"].dropna().median(),
    "ski":  apt["dist_ski_lift_km"].dropna().median(),
}
apt["lat_f"]  = apt["lat"].fillna(med["lat"]).astype(float)
apt["lon_f"]  = apt["lon"].fillna(med["lon"]).astype(float)
apt["alt_f"]  = apt["altitude"].fillna(med["alt"]).astype(float)
apt["dist_f"] = apt["dist_centre_km"].fillna(med["dist"]).astype(float)
apt["ski_f"]  = apt["dist_ski_lift_km"].fillna(med["ski"]).astype(float)

# Année centrée
ANNEE_REF = 2024
apt["annee_f"] = (apt["annee"] - ANNEE_REF).astype(float)

FEATURES = [
    "log_surface",
    "pieces_f",
    "commune_enc",
    "section_enc",
    "annee_f",
    "n_dep_f",
    "alt_f",
    "dist_f",
    "ski_f",
    "lat_f",
    "lon_f",
]

X = apt[FEATURES].astype(float)
y = np.log(apt["valeur"])

print(f"Shape X : {X.shape}, y : {y.shape}")
print(f"Nulls X : {X.isnull().sum().sum()}")

# ── 4. Cross-validation honnête (5-fold) ──────────────────────────────
print("\n=== 4. Cross-validation 5-fold ===")

xgb_params = dict(
    n_estimators=300,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=42,
    n_jobs=-1,
    verbosity=0,
)
model_cv = XGBRegressor(**xgb_params)

kf = KFold(n_splits=5, shuffle=True, random_state=42)
y_cv = cross_val_predict(model_cv, X, y, cv=kf)

mape_cv = mean_absolute_percentage_error(apt["valeur"], np.exp(y_cv))
r2_cv   = r2_score(y, y_cv)
errors  = np.abs(np.exp(y_cv) - apt["valeur"].values) / apt["valeur"].values
p50     = np.percentile(errors, 50)
p80     = np.percentile(errors, 80)
p90     = np.percentile(errors, 90)

print(f"MAPE CV (honnête) : {mape_cv:.1%}")
print(f"R²   CV           : {r2_cv:.3f}")
print(f"P50 erreur        : {p50:.1%}")
print(f"P80 erreur        : {p80:.1%}")
print(f"P90 erreur        : {p90:.1%}")

# Par commune
apt["pred_cv"] = np.exp(y_cv)
apt["err_cv"]  = errors
print("\nMAPE CV par commune :")
print(apt.groupby("commune")["err_cv"].agg(["mean","median","count"]).round(3).sort_values("mean"))

# ── 5. Entraînement final sur tout ────────────────────────────────────
print("\n=== 5. Entraînement final ===")
model_final = XGBRegressor(**xgb_params)
model_final.fit(X, y)
y_train = model_final.predict(X)
mape_tr = mean_absolute_percentage_error(apt["valeur"], np.exp(y_train))
print(f"MAPE train (overfitted ref) : {mape_tr:.1%}")

# ── 6. Index inflation annuel ─────────────────────────────────────────
print("\n=== 6. Index inflation ===")

# Médiane €/m² par année (Chamonix uniquement pour la tendance)
cham = apt[apt["commune"] == "CHAMONIX MONT BLANC"]
emp = cham.groupby("annee")["prix_m2"].median()
emp_idx = (emp / emp[ANNEE_REF]).round(4).to_dict()
print("Index inflation (base 2024=1.0) :")
print(emp_idx)

# Projection 2025 → 2026 (pente linéaire)
years = sorted(emp_idx.keys())
if len(years) >= 3:
    vals = [emp_idx[y] for y in years[-3:]]
    trend = (vals[-1] - vals[0]) / (years[-1] - years[0])
    emp_idx[2026] = round(emp_idx.get(2025, vals[-1]) + trend, 4)
    print(f"Projection 2026 : {emp_idx[2026]:.4f}")

# ── 7. Médiane €/m² par (commune, section) ────────────────────────────
print("\n=== 7. Grille de prix ===")

# Restreint 2023-2025 pour refléter le marché actuel
recent = apt[apt["annee"] >= 2023]
grid_cs = recent.groupby(["commune", "section"])["prix_m2"].agg(["median","count"]).round(0)
print(grid_cs[grid_cs["count"] >= 3])  # sections avec assez de données

# Médiane par commune (fallback si section manque)
grid_c = recent.groupby("commune")["prix_m2"].median().round(0)
print("\nMédiane par commune (2023-2025) :")
print(grid_c)

# ── 8. Fourchette par commune (MAPE CV) ───────────────────────────────
print("\n=== 8. Fourchettes ===")
# Utilise P80 erreur CV comme fourchette ±
fourchette_commune = {}
for com, grp in apt.groupby("commune"):
    p80_com = np.percentile(grp["err_cv"], 80)
    fourchette_commune[com] = round(float(p80_com), 3)
    print(f"  {com}: ±{p80_com:.1%}")

fourchette_global = round(float(p80), 3)
print(f"  Global: ±{fourchette_global:.1%}")

# ── 9. Export JSON pour dashboard JS ──────────────────────────────────
print("\n=== 9. Export JSON ===")

# Grille PM2 : commune → section → médiane €/m² (2023-2025)
pm2_grid = {}
for (com, sec), row in grid_cs.iterrows():
    if row["count"] >= 3:
        pm2_grid.setdefault(com, {})[sec] = int(row["median"])

# Fallback commune-level
for com, pm2 in grid_c.items():
    pm2_grid.setdefault(com, {})["_fallback"] = int(pm2)

# Encodage pour JS : commune → code court
COMMUNE_SHORT = {
    "CHAMONIX MONT BLANC": "Chamonix",
    "LES HOUCHES":         "Les Houches",
    "SAINT GERVAIS LES BAINS": "Saint-Gervais",
    "SALLANCHES":          "Sallanches",
    "PASSY":               "Passy",
    "DOMANCY":             "Domancy",
    "SERVOZ":              "Servoz",
    "ARGENTIERE":          "Argentiere",
}

pm2_js = {}
for com, secs in pm2_grid.items():
    short = COMMUNE_SHORT.get(com, com)
    pm2_js[short] = secs

avm_appart_meta = {
    "_description": "AVM Appartements Vallée Mont-Blanc — calibré DVF 2021-2025",
    "_methodology": f"XGBoost log(valeur), 5-fold CV, {len(apt)} transactions nettoyées",
    "mape_cv": round(mape_cv, 4),
    "r2_cv":   round(r2_cv, 4),
    "p50_err": round(p50, 4),
    "p80_err": round(p80, 4),
    "annee_ref": ANNEE_REF,
    "emp_idx": {str(k): v for k, v in emp_idx.items()},
    "pm2_grid": pm2_js,
    "fourchette_commune": {COMMUNE_SHORT.get(k,k): v for k,v in fourchette_commune.items()},
    "fourchette_global": fourchette_global,
    "pm2_min_filter": PM2_MIN,
    "pm2_max_filter": PM2_MAX,
    "le_commune_classes": list(le_com.classes_),
    "le_section_classes": list(le_sec.classes_),
    "features": FEATURES,
    "annee_min": int(apt["annee"].min()),
    "annee_max": int(apt["annee"].max()),
    "n_samples": len(apt),
    "median_values": {
        "lat": med["lat"], "lon": med["lon"], "alt": med["alt"],
        "dist": med["dist"], "ski": med["ski"]
    }
}

out_json = OUT / "avm_appart_meta.json"
out_json.write_text(json.dumps(avm_appart_meta, indent=2, ensure_ascii=False))
print(f"JSON écrit : {out_json}")

# ── 10. Export pkl ─────────────────────────────────────────────────────
out_pkl = OUT / "avm_appart_model.pkl"
with open(out_pkl, "wb") as f:
    pickle.dump({
        "model": model_final,
        "le_commune": le_com,
        "le_section": le_sec,
        "features": FEATURES,
        "med": med,
        "annee_ref": ANNEE_REF,
        "mape_cv": mape_cv,
    }, f)
print(f"PKL écrit  : {out_pkl}")

print("\n=== RÉSUMÉ ===")
print(f"Échantillon clean : {len(apt)} transactions (2021-2025)")
print(f"MAPE CV honnête   : {mape_cv:.1%}")
print(f"R² CV             : {r2_cv:.3f}")
print(f"Fourchette ±P80   : ±{p80:.1%}")
print("-> Bien meilleur que maisons (20%) car pas de terrain a estimer")
