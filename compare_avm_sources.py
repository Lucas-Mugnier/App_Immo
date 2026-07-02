"""
compare_avm_sources.py
======================
Compare 3 modèles AVM appartements :
  M1 — DVF seul (historique transactions)
  M2 — DVF + annonces en cours (mixed)
  M3 — Annonces en cours seules (prix demandés)

Output : tableau comparatif des prédictions sur les annonces courantes
         + métriques CV pour chaque modèle
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import json, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

BASE     = Path(__file__).parent
DVF_DIR  = BASE / "dvf"
DASH_DIR = BASE / "dashboard-react" / "src" / "data"

# ── Négociation implicite : les prix demandés → prix transaction estimé
LISTING_NEGO_DISCOUNT = 0.04   # -4% en moyenne Chamonix

# ── Paramètres XGBoost communs aux 3 modèles
XGB_PARAMS = dict(
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

# ── Seuils de nettoyage
PM2_MIN, PM2_MAX, SURF_MIN = 3_500, 30_000, 14
ANNEE_REF = 2024

# ─────────────────────────────────────────────────────────────────────────────
# 1. Chargement et nettoyage DVF
# ─────────────────────────────────────────────────────────────────────────────
print("=== 1. DVF ===")
df_raw = pd.read_csv(DVF_DIR / "dvf_clean.csv")
dvf = df_raw[df_raw["type_local"] == "appart"].copy()
dvf = dvf[
    dvf["prix_m2"].between(PM2_MIN, PM2_MAX) &
    (dvf["surface"] >= SURF_MIN) &
    (dvf["surf_terrain"].fillna(0) == 0) &
    dvf["valeur"].notna() &
    dvf["surface"].notna()
].copy()
print(f"DVF nettoyé : {len(dvf)} transactions")
print(f"Communes : {dvf['commune'].value_counts().to_dict()}")

# Médians géo par commune (utilisés comme fallback pour les annonces)
geo_medians = dvf.groupby("commune").agg(
    lat=("lat", "median"),
    lon=("lon", "median"),
    alt=("altitude", "median"),
    dist=("dist_centre_km", "median"),
    ski=("dist_ski_lift_km", "median"),
).to_dict("index")

GLOBAL_MED = {
    "lat":  dvf["lat"].dropna().median(),
    "lon":  dvf["lon"].dropna().median(),
    "alt":  dvf["altitude"].dropna().median(),
    "dist": dvf["dist_centre_km"].dropna().median(),
    "ski":  dvf["dist_ski_lift_km"].dropna().median(),
}

def geo_for_commune(commune_str: str) -> dict:
    """Retourne les médians géo pour une commune, fallback global."""
    c = commune_str.upper()
    if c in geo_medians:
        return geo_medians[c]
    # Chamonix par défaut (majorité des biens)
    return GLOBAL_MED

# Mapping location courte → nom DVF
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
# 2. Chargement annonces en cours
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 2. Annonces en cours ===")
listings_raw = json.loads((DASH_DIR / "listings.json").read_text(encoding="utf-8"))
listings = [l for l in listings_raw if not l.get("is_structured", False)]

lst = pd.DataFrame([{
    "id":       l["id"],
    "title":    l.get("title", ""),
    "price":    l["price"],
    "surface":  l["surface"],
    "rooms":    l.get("rooms", 2),
    "commune":  COMMUNE_MAP.get(l.get("location", "Chamonix"), "CHAMONIX MONT BLANC"),
    "avm_pred_current": l.get("avm_pred"),   # prédiction actuelle pour référence
    "avm_ratio_current": l.get("avm_ratio"),
} for l in listings])

lst = lst[
    (lst["price"] > 0) &
    (lst["surface"] >= SURF_MIN) &
    (lst["price"] / lst["surface"]).between(PM2_MIN, PM2_MAX)
].copy()
lst["pm2"] = lst["price"] / lst["surface"]
print(f"Annonces valides : {len(lst)}")
print(f"Communes : {lst['commune'].value_counts().to_dict()}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Construction des datasets d'entraînement
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 3. Feature engineering ===")

# Encodeurs communs — ajustons sur l'union DVF + listings pour éviter les NaN
all_communes = pd.concat([
    dvf["commune"].fillna("CHAMONIX MONT BLANC"),
    lst["commune"].fillna("CHAMONIX MONT BLANC"),
])
all_sections = dvf["section"].fillna("G")

le_com = LabelEncoder().fit(all_communes)
le_sec = LabelEncoder().fit(all_sections)

SECTION_DEFAULT_ENC = int(le_sec.transform(["G"])[0])

def make_dvf_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features complètes DVF (avec géo réelle)."""
    d = df.copy()
    d["commune_enc"]  = le_com.transform(d["commune"].fillna("CHAMONIX MONT BLANC"))
    d["section_enc"]  = le_sec.transform(d["section"].fillna("G"))
    d["log_surface"]  = np.log(d["surface"].clip(1))
    d["pieces_f"]     = d["pieces"].fillna(d["pieces"].median()).clip(1, 10)
    d["n_dep_f"]      = d["n_dependances"].fillna(0).clip(0, 5).astype(float)
    d["annee_f"]      = (d["annee"] - ANNEE_REF).astype(float)
    d["lat_f"]        = d["lat"].fillna(GLOBAL_MED["lat"]).astype(float)
    d["lon_f"]        = d["lon"].fillna(GLOBAL_MED["lon"]).astype(float)
    d["alt_f"]        = d["altitude"].fillna(GLOBAL_MED["alt"]).astype(float)
    d["dist_f"]       = d["dist_centre_km"].fillna(GLOBAL_MED["dist"]).astype(float)
    d["ski_f"]        = d["dist_ski_lift_km"].fillna(GLOBAL_MED["ski"]).astype(float)
    return d

FEATURES_FULL = [
    "log_surface", "pieces_f", "commune_enc", "section_enc",
    "annee_f", "n_dep_f", "alt_f", "dist_f", "ski_f", "lat_f", "lon_f",
]

# Features communes DVF + listings (sans section, sans géo précise, sans dépendances)
FEATURES_COMMON = [
    "log_surface", "pieces_f", "commune_enc", "annee_f",
    "alt_f", "dist_f", "ski_f",
]

def make_listing_features(df: pd.DataFrame, annee: float = 2026.0) -> pd.DataFrame:
    """Features listings — géo approchée par médian de commune."""
    d = df.copy()
    d["commune_enc"] = le_com.transform(d["commune"].fillna("CHAMONIX MONT BLANC"))
    d["section_enc"] = SECTION_DEFAULT_ENC
    d["log_surface"] = np.log(d["surface"].clip(1))
    d["pieces_f"]    = d["rooms"].clip(1, 10).astype(float)
    d["n_dep_f"]     = 0.0
    d["annee_f"]     = annee - ANNEE_REF

    lats, lons, alts, dists, skis = [], [], [], [], []
    for _, row in d.iterrows():
        g = geo_for_commune(row["commune"])
        lats.append(g["lat"]); lons.append(g["lon"]); alts.append(g["alt"])
        dists.append(g["dist"]); skis.append(g["ski"])
    d["lat_f"]  = lats
    d["lon_f"]  = lons
    d["alt_f"]  = alts
    d["dist_f"] = dists
    d["ski_f"]  = skis
    return d

# ── Préparer les données DVF (format commun)
dvf_feat = make_dvf_features(dvf)
dvf_feat["valeur_train"] = dvf["valeur"]

# ── Préparer les "pseudo-transactions" listings
# Prix demandé - négociation implicite = transaction estimée
lst_feat = make_listing_features(lst)
lst_feat["valeur_train"] = lst["price"] * (1 - LISTING_NEGO_DISCOUNT)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Entraînement + CV des 3 modèles
# ─────────────────────────────────────────────────────────────────────────────

def train_and_cv(X: pd.DataFrame, y: np.ndarray, label: str):
    """Entraîne, cross-valide et retourne (model_final, mape_cv, r2_cv, y_cv_exp)."""
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    mdl_cv = XGBRegressor(**XGB_PARAMS)
    y_cv   = cross_val_predict(mdl_cv, X, y, cv=kf)

    y_true_exp  = np.exp(y)
    y_cv_exp    = np.exp(y_cv)
    mape_cv     = mean_absolute_percentage_error(y_true_exp, y_cv_exp)
    r2_cv       = r2_score(y, y_cv)
    errors      = np.abs(y_cv_exp - y_true_exp) / y_true_exp
    p50, p80    = np.percentile(errors, 50), np.percentile(errors, 80)

    print(f"\n  [{label}]")
    print(f"    n           = {len(X)}")
    print(f"    MAPE CV     = {mape_cv:.1%}")
    print(f"    R² CV       = {r2_cv:.3f}")
    print(f"    P50 erreur  = {p50:.1%}")
    print(f"    P80 erreur  = {p80:.1%}")

    mdl_final = XGBRegressor(**XGB_PARAMS)
    mdl_final.fit(X, y)
    return mdl_final, mape_cv, r2_cv, p80

print("\n=== 4. Cross-validation des 3 modèles ===")

# M1 — DVF seul (features complètes)
X_m1 = dvf_feat[FEATURES_FULL].astype(float)
y_m1 = np.log(dvf_feat["valeur_train"])
m1, mape_m1, r2_m1, p80_m1 = train_and_cv(X_m1, y_m1, "M1 — DVF seul (features complètes)")

# M2 — DVF + listings (features communes)
X_dvf_common  = dvf_feat[FEATURES_COMMON].astype(float)
X_lst_common  = lst_feat[FEATURES_COMMON].astype(float)
X_m2 = pd.concat([X_dvf_common, X_lst_common], ignore_index=True)
y_m2 = np.log(pd.concat([dvf_feat["valeur_train"], lst_feat["valeur_train"]], ignore_index=True))
m2, mape_m2, r2_m2, p80_m2 = train_and_cv(X_m2, y_m2, "M2 — DVF + listings (features communes)")

# M3 — Listings seuls (features communes)
X_m3 = lst_feat[FEATURES_COMMON].astype(float)
y_m3 = np.log(lst_feat["valeur_train"])
m3, mape_m3, r2_m3, p80_m3 = train_and_cv(X_m3, y_m3, "M3 — Listings seuls")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Prédictions comparées sur les annonces courantes
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 5. Comparaison des prédictions sur annonces courantes ===\n")

# Préparer features pour prédire sur les listings
X_pred_full   = make_listing_features(lst)[FEATURES_FULL].astype(float)
X_pred_common = make_listing_features(lst)[FEATURES_COMMON].astype(float)

pred_m1 = np.exp(m1.predict(X_pred_full))
pred_m2 = np.exp(m2.predict(X_pred_common))
pred_m3 = np.exp(m3.predict(X_pred_common))

results = lst.copy()
results["pred_m1"] = pred_m1.round(0).astype(int)
results["pred_m2"] = pred_m2.round(0).astype(int)
results["pred_m3"] = pred_m3.round(0).astype(int)
results["ratio_m1"] = (results["price"] / results["pred_m1"]).round(3)
results["ratio_m2"] = (results["price"] / results["pred_m2"]).round(3)
results["ratio_m3"] = (results["price"] / results["pred_m3"]).round(3)
results["delta_m2_vs_m1"] = ((results["pred_m2"] - results["pred_m1"]) / results["pred_m1"] * 100).round(1)
results["delta_m3_vs_m1"] = ((results["pred_m3"] - results["pred_m1"]) / results["pred_m1"] * 100).round(1)

# Affichage tableau
col_w = [30, 8, 7, 10, 10, 10, 9, 9, 10, 10]
header = ["Bien", "Prix", "m²", "M1-DVF", "M2-Mix", "M3-Lst", "R M1", "R M2", "ΔM2/M1", "ΔM3/M1"]
sep = "─" * sum(col_w)
print(sep)
print("".join(f"{h:<{w}}" for h, w in zip(header, col_w)))
print(sep)

for _, r in results.sort_values("price").iterrows():
    def eur_k(v): return f"{v/1000:.0f}k€"
    def pct(v): return f"{v:+.1f}%"
    row = [
        r["title"][:29],
        eur_k(r["price"]),
        f"{r['surface']:.0f}",
        eur_k(r["pred_m1"]),
        eur_k(r["pred_m2"]),
        eur_k(r["pred_m3"]),
        f"{r['ratio_m1']:.2f}",
        f"{r['ratio_m2']:.2f}",
        pct(r["delta_m2_vs_m1"]),
        pct(r["delta_m3_vs_m1"]),
    ]
    print("".join(f"{v:<{w}}" for v, w in zip(row, col_w)))

print(sep)

# ─────────────────────────────────────────────────────────────────────────────
# 6. Résumé des métriques
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 6. Résumé ===\n")
print(f"{'Modèle':<35}  {'MAPE CV':>8}  {'R² CV':>6}  {'P80':>6}  {'n train':>8}")
print("─" * 75)
print(f"{'M1 — DVF seul (11 features, géo)':<35}  {mape_m1:>7.1%}  {r2_m1:>6.3f}  {p80_m1:>5.1%}  {len(X_m1):>8}")
print(f"{'M2 — DVF + listings (7 features)':<35}  {mape_m2:>7.1%}  {r2_m2:>6.3f}  {p80_m2:>5.1%}  {len(X_m2):>8}")
print(f"{'M3 — Listings seuls (7 features)':<35}  {mape_m3:>7.1%}  {r2_m3:>6.3f}  {p80_m3:>5.1%}  {len(X_m3):>8}")

print(f"\nAnnonces : discount négociation appliqué = -{LISTING_NEGO_DISCOUNT*100:.0f}%")
print("Note : M3 a très peu de données (les listings), son MAPE CV est en LOO-like → moins fiable.")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Insights : biens où M1 et M2 divergent le plus
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 7. Plus grandes divergences M1 vs M2 ===\n")
top_div = results.reindex(results["delta_m2_vs_m1"].abs().nlargest(10).index)
for _, r in top_div.iterrows():
    sign = "↑" if r["delta_m2_vs_m1"] > 0 else "↓"
    print(f"  {r['title'][:40]:<40}  M2 {sign} {abs(r['delta_m2_vs_m1']):.1f}% vs M1"
          f"  (prix {r['price']/1000:.0f}k€, M1={r['pred_m1']/1000:.0f}k€, M2={r['pred_m2']/1000:.0f}k€)")

print("\nFin de l'analyse.")
