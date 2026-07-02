"""
build_avm_maison_cham.py
=========================
AVM Maisons Chamonix uniquement — 2 passes ratio-clip [0.65-1.20]
Export : dvf/avm_maison_cham_model.pkl + dvf/avm_maison_cham_meta.json
"""
import pandas as pd, numpy as np, json, pickle, sys
from pathlib import Path
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor
sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
DVF  = BASE / "dvf"

# ── 1. Chargement ─────────────────────────────────────────────────────────────
df  = pd.read_csv(DVF / "dvf_clean.csv")
raw = df[(df["type_local"]=="maison") &
         (df["commune"]=="CHAMONIX MONT BLANC")].dropna(subset=["valeur","surface"]).copy()
raw["pm2"] = raw["valeur"] / raw["surface"]
print(f"Chamonix maisons brut : {len(raw)}")

# ── 2. Filtre PM2 base [5 000-40 000] ─────────────────────────────────────────
PM2_MIN, PM2_MAX = 5_000, 40_000
base = raw[(raw["pm2"] >= PM2_MIN) & (raw["pm2"] <= PM2_MAX)].copy().reset_index(drop=True)
print(f"Apres PM2 [{PM2_MIN:,}-{PM2_MAX:,}] : {len(base)} tx")

# ── 3. Features ───────────────────────────────────────────────────────────────
ANNEE_REF = 2024
le_sec = LabelEncoder()
base["sec_enc"]  = le_sec.fit_transform(base["section"])
base["log_surf"] = np.log(base["surface"].clip(1))
base["pieces_f"] = base["pieces"].fillna(4.0).clip(1,12)
base["annee_f"]  = (base["annee"] - ANNEE_REF).astype(float)
base["ndep_f"]   = base["n_dependances"].clip(0,5).astype(float)
base["lots_f"]   = base["nb_lots"].clip(0,4).astype(float)
base["has_ter"]  = (base["surf_terrain"].fillna(0) > 0).astype(float)
base["log_ter"]  = np.log1p(base["surf_terrain"].fillna(0))

med = {
    "lat":  base["lat"].dropna().median(),
    "lon":  base["lon"].dropna().median(),
    "alt":  base["altitude"].dropna().median(),
    "dist": base["dist_centre_km"].dropna().median(),
    "ski":  base["dist_ski_lift_km"].dropna().median(),
}
base["lat_f"]  = base["lat"].fillna(med["lat"]).astype(float)
base["lon_f"]  = base["lon"].fillna(med["lon"]).astype(float)
base["alt_f"]  = base["altitude"].fillna(med["alt"]).astype(float)
base["dist_f"] = base["dist_centre_km"].fillna(med["dist"]).astype(float)
base["ski_f"]  = base["dist_ski_lift_km"].fillna(med["ski"]).astype(float)

FEATS = ["log_surf","pieces_f","sec_enc","annee_f","ndep_f","lots_f",
         "has_ter","log_ter","lat_f","lon_f","alt_f","dist_f","ski_f"]

XGB_PARAMS = dict(n_estimators=400, max_depth=5, learning_rate=0.04,
                  subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
                  reg_alpha=0.1, reg_lambda=1.0, random_state=42, n_jobs=-1, verbosity=0)

kf  = KFold(n_splits=5, shuffle=True, random_state=42)
xgb = XGBRegressor(**XGB_PARAMS)

# ── 4. Passe 1 ────────────────────────────────────────────────────────────────
X0 = base[FEATS].astype(float)
y0 = np.log(base["valeur"])
y_cv0    = cross_val_predict(xgb, X0, y0, cv=kf)
base["ratio_p1"] = np.exp(y_cv0) / base["valeur"]
mape_p1  = mean_absolute_percentage_error(base["valeur"], np.exp(y_cv0))
print(f"\nPasse 1 : MAPE {mape_p1:.1%}  n={len(base)}")

# ── 5. Ratio-clip [0.65-1.20] ────────────────────────────────────────────────
RATIO_LO, RATIO_HI = 0.65, 1.20
f_ratio = (base["ratio_p1"] < RATIO_LO) | (base["ratio_p1"] > RATIO_HI)
n_lo    = (base["ratio_p1"] < RATIO_LO).sum()
n_hi    = (base["ratio_p1"] > RATIO_HI).sum()
print(f"Ratio-clip [{RATIO_LO}-{RATIO_HI}] : -{f_ratio.sum()} tx ({n_lo} chalets luxe + {n_hi} anomalies)")

clean = base[~f_ratio].copy().reset_index(drop=True)
print(f"Echantillon final : {len(clean)} tx")

# Recompute features sur sous-ensemble
clean["sec_enc"]  = le_sec.transform(clean["section"])
clean["log_surf"] = np.log(clean["surface"].clip(1))
clean["pieces_f"] = clean["pieces"].fillna(4.0).clip(1,12)
clean["annee_f"]  = (clean["annee"] - ANNEE_REF).astype(float)
clean["ndep_f"]   = clean["n_dependances"].clip(0,5).astype(float)
clean["lots_f"]   = clean["nb_lots"].clip(0,4).astype(float)
clean["has_ter"]  = (clean["surf_terrain"].fillna(0) > 0).astype(float)
clean["log_ter"]  = np.log1p(clean["surf_terrain"].fillna(0))
clean["lat_f"]    = clean["lat"].fillna(med["lat"]).astype(float)
clean["lon_f"]    = clean["lon"].fillna(med["lon"]).astype(float)
clean["alt_f"]    = clean["altitude"].fillna(med["alt"]).astype(float)
clean["dist_f"]   = clean["dist_centre_km"].fillna(med["dist"]).astype(float)
clean["ski_f"]    = clean["dist_ski_lift_km"].fillna(med["ski"]).astype(float)

X = clean[FEATS].astype(float)
y = np.log(clean["valeur"])

# ── 6. Passe 2 : CV + train final ────────────────────────────────────────────
y_cv     = cross_val_predict(xgb, X, y, cv=kf)
clean["pred_cv"]  = np.exp(y_cv)
clean["err_pct"]  = (clean["pred_cv"] - clean["valeur"]).abs() / clean["valeur"]
mape_cv  = mean_absolute_percentage_error(clean["valeur"], clean["pred_cv"])
r2_cv    = r2_score(y, y_cv)
p50      = np.percentile(clean["err_pct"], 50)
p80      = np.percentile(clean["err_pct"], 80)
print(f"Passe 2 : MAPE {mape_cv:.1%}  R2 {r2_cv:.3f}  P50 {p50:.1%}  P80 {p80:.1%}")

xgb.fit(X, y)

# ── 7. Stats marché ──────────────────────────────────────────────────────────
emp = clean.groupby("annee")["pm2"].median()
emp_idx = (emp / emp[ANNEE_REF]).round(4).to_dict()
years = sorted(emp_idx.keys())
if len(years) >= 2:
    trend = emp_idx[years[-1]] - emp_idx[years[-2]]
    emp_idx[2026] = round(emp_idx[years[-1]] + trend, 4)

recent   = clean[clean["annee"] >= 2023]
pm2_sec  = recent.groupby("section")["pm2"].median().round(0).to_dict()
pm2_glob = int(recent["pm2"].median())

print(f"\nPM2 par section (2023-2025): {pm2_sec}")
print(f"Index inflation: {emp_idx}")

# ── 8. Export PKL ────────────────────────────────────────────────────────────
pkl_path = DVF / "avm_maison_cham_model.pkl"
with open(pkl_path, "wb") as f:
    pickle.dump({
        "model":    xgb,
        "le_sec":   le_sec,
        "features": FEATS,
        "med":      med,
        "annee_ref":ANNEE_REF,
        "mape_cv":  mape_cv,
        "r2_cv":    r2_cv,
        "p80_err":  p80,
        "pm2_sec":  {k: int(v) for k, v in pm2_sec.items()},
        "pm2_min":  PM2_MIN,
        "pm2_max":  PM2_MAX,
        "ratio_lo": RATIO_LO,
        "ratio_hi": RATIO_HI,
        "n_train":  len(clean),
        "emp_idx":  {str(k): v for k, v in emp_idx.items()},
    }, f)
print(f"\nPKL : {pkl_path}")

# ── 9. Export meta JSON ──────────────────────────────────────────────────────
meta = {
    "_desc": f"AVM Maisons Chamonix — PM2 {PM2_MIN:,}-{PM2_MAX:,} + ratio [{RATIO_LO}-{RATIO_HI}] — XGBoost 5-fold CV",
    "n_train":   len(clean),
    "mape_cv":   round(mape_cv, 4),
    "r2_cv":     round(r2_cv, 4),
    "p50_err":   round(p50, 4),
    "p80_err":   round(p80, 4),
    "pm2_global":pm2_glob,
    "pm2_sec":   {k: int(v) for k, v in pm2_sec.items()},
    "emp_idx":   {str(k): v for k, v in emp_idx.items()},
    "le_sec_classes": list(le_sec.classes_),
    "features":  FEATS,
    "medians":   med,
}
(DVF / "avm_maison_cham_meta.json").write_text(
    json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"JSON: {DVF/'avm_maison_cham_meta.json'}")
print(f"\n=== RESUME ===")
print(f"Maisons Chamonix : {len(clean)} tx (sur {len(raw)} brut)")
print(f"MAPE CV : {mape_cv:.1%}  R2 : {r2_cv:.3f}  P80 : ±{p80:.1%}")
