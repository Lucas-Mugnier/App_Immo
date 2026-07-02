"""
validate_avm_sources.py
=======================
Validation hors-échantillon des 3 modèles AVM sur des transactions DVF réelles.

Protocole :
  - DVF divisé en 80% train / 20% test (aléatoire, seed fixe)
  - M1 entraîné sur DVF_train (features complètes)
  - M2 entraîné sur DVF_train + listings (features communes)
  - M3 entraîné sur listings seuls (features communes)
  - Les 3 prédisent sur DVF_test (transactions réelles)
  - On mesure l'erreur par rapport au prix de vente effectif
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import json, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

BASE     = Path(__file__).parent
DVF_DIR  = BASE / "dvf"
DASH_DIR = BASE / "dashboard-react" / "src" / "data"

LISTING_NEGO_DISCOUNT = 0.04
ANNEE_REF             = 2024
PM2_MIN, PM2_MAX, SURF_MIN = 3_500, 30_000, 14

XGB_PARAMS = dict(
    n_estimators=300, max_depth=5, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
    reg_alpha=0.1, reg_lambda=1.0, random_state=42, n_jobs=-1, verbosity=0,
)

FEATURES_FULL   = ["log_surface","pieces_f","commune_enc","section_enc",
                   "annee_f","n_dep_f","alt_f","dist_f","ski_f","lat_f","lon_f"]
FEATURES_COMMON = ["log_surface","pieces_f","commune_enc","annee_f",
                   "alt_f","dist_f","ski_f"]

COMMUNE_MAP = {
    "Chamonix":       "CHAMONIX MONT BLANC",
    "Les Houches":    "LES HOUCHES",
    "Saint-Gervais":  "SAINT GERVAIS LES BAINS",
    "Sallanches":     "SALLANCHES",
    "Passy":          "PASSY",
    "Domancy":        "DOMANCY",
    "Servoz":         "SERVOZ",
    "Argentière":     "ARGENTIERE",
    "Argentiere":     "ARGENTIERE",
}

# ─────────────────────────────────────────────────────────────────────────────
print("=== 1. Chargement ===")
df_raw = pd.read_csv(DVF_DIR / "dvf_clean.csv")
dvf = df_raw[df_raw["type_local"] == "appart"].copy()
dvf = dvf[
    dvf["prix_m2"].between(PM2_MIN, PM2_MAX) &
    (dvf["surface"] >= SURF_MIN) &
    (dvf["surf_terrain"].fillna(0) == 0) &
    dvf["valeur"].notna() & dvf["surface"].notna()
].copy()
print(f"DVF total : {len(dvf)} transactions")

listings_raw = json.loads((DASH_DIR / "listings.json").read_text(encoding="utf-8"))
listings = [l for l in listings_raw if not l.get("is_structured", False)]
lst = pd.DataFrame([{
    "id":      l["id"],
    "title":   l.get("title",""),
    "price":   l["price"],
    "surface": l["surface"],
    "rooms":   l.get("rooms", 2),
    "commune": COMMUNE_MAP.get(l.get("location","Chamonix"), "CHAMONIX MONT BLANC"),
} for l in listings])
lst = lst[
    (lst["price"] > 0) & (lst["surface"] >= SURF_MIN) &
    (lst["price"] / lst["surface"]).between(PM2_MIN, PM2_MAX)
].copy()
print(f"Listings  : {len(lst)}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 2. Split DVF 80/20 ===")
dvf_train, dvf_test = train_test_split(dvf, test_size=0.20, random_state=42)
print(f"Train : {len(dvf_train)}   Test : {len(dvf_test)}")

# Médians géo par commune calculés sur DVF_TRAIN uniquement (pas de fuite de données)
geo_medians = dvf_train.groupby("commune").agg(
    lat=("lat","median"), lon=("lon","median"),
    alt=("altitude","median"), dist=("dist_centre_km","median"),
    ski=("dist_ski_lift_km","median"),
).to_dict("index")
GLOBAL_MED = dict(
    lat=dvf_train["lat"].median(), lon=dvf_train["lon"].median(),
    alt=dvf_train["altitude"].median(), dist=dvf_train["dist_centre_km"].median(),
    ski=dvf_train["dist_ski_lift_km"].median(),
)

def geo_commune(commune):
    c = str(commune).upper()
    return geo_medians.get(c, GLOBAL_MED)

# Encodeurs ajustés sur train + listings (pour que M3 n'ait pas de NaN)
all_communes = pd.concat([dvf_train["commune"].fillna("CHAMONIX MONT BLANC"),
                          lst["commune"].fillna("CHAMONIX MONT BLANC")])
le_com = LabelEncoder().fit(all_communes)
le_sec = LabelEncoder().fit(dvf_train["section"].fillna("G"))
SEC_DEFAULT = int(le_sec.transform(["G"])[0])

def featurize_dvf(df, full=True):
    d = df.copy()
    d["commune_enc"] = le_com.transform(d["commune"].fillna("CHAMONIX MONT BLANC"))
    d["section_enc"] = le_sec.transform(d["section"].fillna("G"))
    d["log_surface"] = np.log(d["surface"].clip(1))
    d["pieces_f"]    = d["pieces"].fillna(d["pieces"].median()).clip(1,10)
    d["n_dep_f"]     = d["n_dependances"].fillna(0).clip(0,5).astype(float)
    d["annee_f"]     = (d["annee"] - ANNEE_REF).astype(float)
    d["lat_f"]       = d["lat"].fillna(GLOBAL_MED["lat"]).astype(float)
    d["lon_f"]       = d["lon"].fillna(GLOBAL_MED["lon"]).astype(float)
    d["alt_f"]       = d["altitude"].fillna(GLOBAL_MED["alt"]).astype(float)
    d["dist_f"]      = d["dist_centre_km"].fillna(GLOBAL_MED["dist"]).astype(float)
    d["ski_f"]       = d["dist_ski_lift_km"].fillna(GLOBAL_MED["ski"]).astype(float)
    return d[FEATURES_FULL if full else FEATURES_COMMON].astype(float)

def featurize_listings(df):
    d = df.copy()
    d["commune_enc"] = le_com.transform(d["commune"].fillna("CHAMONIX MONT BLANC"))
    d["section_enc"] = SEC_DEFAULT
    d["log_surface"] = np.log(d["surface"].clip(1))
    d["pieces_f"]    = d["rooms"].clip(1,10).astype(float)
    d["n_dep_f"]     = 0.0
    d["annee_f"]     = 2026.0 - ANNEE_REF
    for col, key in [("alt_f","alt"),("dist_f","dist"),("ski_f","ski"),
                     ("lat_f","lat"),("lon_f","lon")]:
        d[col] = d["commune"].apply(lambda c: geo_commune(c)[key])
    return d[FEATURES_COMMON].astype(float)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 3. Entraînement des 3 modèles ===")

# M1 — DVF train (features complètes)
X1_tr = featurize_dvf(dvf_train, full=True)
y1_tr = np.log(dvf_train["valeur"].values)
m1 = XGBRegressor(**XGB_PARAMS).fit(X1_tr, y1_tr)
print(f"  M1 entraîné : {len(X1_tr)} transactions, {len(FEATURES_FULL)} features")

# M2 — DVF train + listings (features communes)
X_dvf_c  = featurize_dvf(dvf_train, full=False)
X_lst_c  = featurize_listings(lst)
X2_tr    = pd.concat([X_dvf_c, X_lst_c], ignore_index=True)
y_dvf_c  = np.log(dvf_train["valeur"].values)
y_lst_c  = np.log(lst["price"].values * (1 - LISTING_NEGO_DISCOUNT))
y2_tr    = np.concatenate([y_dvf_c, y_lst_c])
m2 = XGBRegressor(**XGB_PARAMS).fit(X2_tr, y2_tr)
print(f"  M2 entraîné : {len(X2_tr)} points ({len(X_dvf_c)} DVF + {len(X_lst_c)} listings), {len(FEATURES_COMMON)} features")

# M3 — Listings seuls
X3_tr = X_lst_c.copy()
y3_tr = y_lst_c.copy()
m3 = XGBRegressor(**XGB_PARAMS).fit(X3_tr, y3_tr)
print(f"  M3 entraîné : {len(X3_tr)} listings, {len(FEATURES_COMMON)} features")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 4. Validation sur DVF test (transactions réelles) ===")

X_test_full   = featurize_dvf(dvf_test, full=True)
X_test_common = featurize_dvf(dvf_test, full=False)
y_test_real   = dvf_test["valeur"].values   # prix de vente effectif

pred_m1 = np.exp(m1.predict(X_test_full))
pred_m2 = np.exp(m2.predict(X_test_common))
pred_m3 = np.exp(m3.predict(X_test_common))

def metrics(pred, y_true, label):
    err     = np.abs(pred - y_true) / y_true
    mape    = err.mean()
    p50     = np.percentile(err, 50)
    p80     = np.percentile(err, 80)
    r2      = r2_score(np.log(y_true), np.log(pred))
    bias    = (pred / y_true - 1).mean()         # biais moyen (+ = sur-estime)
    return dict(mape=mape, p50=p50, p80=p80, r2=r2, bias=bias, label=label)

m = [
    metrics(pred_m1, y_test_real, "M1 — DVF seul      (11 features)"),
    metrics(pred_m2, y_test_real, "M2 — DVF + listings (7 features)"),
    metrics(pred_m3, y_test_real, "M3 — Listings seuls (7 features)"),
]

print(f"\n{'Modèle':<35}  {'MAPE':>7}  {'P50':>6}  {'P80':>6}  {'R²':>6}  {'Biais':>7}")
print("─" * 75)
for r in m:
    print(f"  {r['label']:<33}  {r['mape']:>6.1%}  {r['p50']:>5.1%}  {r['p80']:>5.1%}"
          f"  {r['r2']:>6.3f}  {r['bias']:>+6.1%}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 5. Détail par tranche de prix ===\n")

dvf_test2 = dvf_test.copy()
dvf_test2["pred_m1"] = pred_m1
dvf_test2["pred_m2"] = pred_m2
dvf_test2["pred_m3"] = pred_m3
dvf_test2["err_m1"]  = np.abs(pred_m1 - y_test_real) / y_test_real
dvf_test2["err_m2"]  = np.abs(pred_m2 - y_test_real) / y_test_real
dvf_test2["err_m3"]  = np.abs(pred_m3 - y_test_real) / y_test_real

bins   = [0, 150_000, 300_000, 500_000, 800_000, 2_000_000]
labels = ["<150k", "150-300k", "300-500k", "500-800k", ">800k"]
dvf_test2["tranche"] = pd.cut(dvf_test2["valeur"], bins=bins, labels=labels)

print(f"{'Tranche':>12}  {'n':>5}  {'MAPE M1':>8}  {'MAPE M2':>8}  {'MAPE M3':>8}  {'Meilleur':>10}")
print("─" * 65)
for tr in labels:
    grp = dvf_test2[dvf_test2["tranche"] == tr]
    if len(grp) < 3:
        continue
    e1 = grp["err_m1"].mean()
    e2 = grp["err_m2"].mean()
    e3 = grp["err_m3"].mean()
    best_val = min(e1, e2, e3)
    best = "M1" if best_val == e1 else ("M2" if best_val == e2 else "M3")
    print(f"  {tr:>10}  {len(grp):>5}  {e1:>7.1%}  {e2:>7.1%}  {e3:>7.1%}  {best:>10}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 6. Détail par surface ===\n")

bins_s   = [0, 25, 40, 60, 90, 500]
labels_s = ["Studio(<25)", "T2(25-40)", "T3(40-60)", "T4(60-90)", "Grand(>90)"]
dvf_test2["cat_surf"] = pd.cut(dvf_test2["surface"], bins=bins_s, labels=labels_s)

print(f"{'Catégorie':>14}  {'n':>5}  {'MAPE M1':>8}  {'MAPE M2':>8}  {'MAPE M3':>8}  {'Meilleur':>10}")
print("─" * 70)
for cat in labels_s:
    grp = dvf_test2[dvf_test2["cat_surf"] == cat]
    if len(grp) < 3:
        continue
    e1 = grp["err_m1"].mean()
    e2 = grp["err_m2"].mean()
    e3 = grp["err_m3"].mean()
    best_val = min(e1, e2, e3)
    best = "M1" if best_val == e1 else ("M2" if best_val == e2 else "M3")
    print(f"  {cat:>12}  {len(grp):>5}  {e1:>7.1%}  {e2:>7.1%}  {e3:>7.1%}  {best:>10}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 7. Détail par commune ===\n")

print(f"{'Commune':>28}  {'n':>5}  {'MAPE M1':>8}  {'MAPE M2':>8}  {'MAPE M3':>8}  {'Meilleur':>10}")
print("─" * 80)
for com, grp in dvf_test2.groupby("commune"):
    if len(grp) < 5:
        continue
    e1 = grp["err_m1"].mean()
    e2 = grp["err_m2"].mean()
    e3 = grp["err_m3"].mean()
    best_val = min(e1, e2, e3)
    best = "M1" if best_val == e1 else ("M2" if best_val == e2 else "M3")
    print(f"  {com:>26}  {len(grp):>5}  {e1:>7.1%}  {e2:>7.1%}  {e3:>7.1%}  {best:>10}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 8. Résumé synthèse ===\n")
winner_counts = {"M1": 0, "M2": 0, "M3": 0}
for tr in labels:
    grp = dvf_test2[dvf_test2["tranche"] == tr]
    if len(grp) < 3: continue
    e1,e2,e3 = grp["err_m1"].mean(),grp["err_m2"].mean(),grp["err_m3"].mean()
    best_val = min(e1,e2,e3)
    winner_counts["M1" if best_val==e1 else ("M2" if best_val==e2 else "M3")] += 1
for cat in labels_s:
    grp = dvf_test2[dvf_test2["cat_surf"] == cat]
    if len(grp) < 3: continue
    e1,e2,e3 = grp["err_m1"].mean(),grp["err_m2"].mean(),grp["err_m3"].mean()
    best_val = min(e1,e2,e3)
    winner_counts["M1" if best_val==e1 else ("M2" if best_val==e2 else "M3")] += 1

best_overall = m[0] if m[0]["mape"] <= m[1]["mape"] else m[1]
if m[2]["mape"] < best_overall["mape"]: best_overall = m[2]

print(f"  Meilleur MAPE global  : {best_overall['label'].strip()}")
print(f"  Victoires par segment : M1={winner_counts['M1']}  M2={winner_counts['M2']}  M3={winner_counts['M3']}")
print(f"\n  Biais moyen (+ = sur-estime le prix de vente) :")
for r in m:
    print(f"    {r['label'].strip():<35}  biais {r['bias']:>+.1%}")
print(f"\n  Note : M3 biaisé +{LISTING_NEGO_DISCOUNT:.0%} attendu (prix demandés vs transactions)")
