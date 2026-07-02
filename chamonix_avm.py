# -*- coding: utf-8 -*-
"""
chamonix_avm.py
Modele AVM dedie Chamonix — val_bati + val_terrain par section x PLU
  - Nettoyage  : passe 1 composite ±50%/+100% par section
                 passes 2-4 iteratives par résidus OOF (seuils 60/50/45%)
  - Cible      : log(valeur totale)
  - Features   : val_bati + val_terrain (section x PLU) + structurel
  - CV         : 5-fold honnete, section_te calculé sur fold train uniquement
  - Sortie     : dvf/chamonix_avm.html
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import warnings; warnings.filterwarnings("ignore")
import os, json
import pandas as pd, numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.model_selection import KFold
from xgboost import XGBRegressor

BASE    = os.path.dirname(os.path.abspath(__file__))
DVF_DIR = os.path.join(BASE, "dvf")
BG = "#0d0f1a"; PBG = "#13162a"; GRID = "#1e2340"; TXT = "#e2e8f0"
SEC_COLOR = {"A":"#a78bfa","B":"#60a5fa","C":"#34d399","D":"#fbbf24",
             "E":"#f97316","G":"#ef4444"}

# ── Terrain reference Chamonix (section x PLU) ────────────────────────────────
TR = json.load(open(os.path.join(DVF_DIR, "terrain_ref_prix.json")))
def ter_U(section):
    s = str(section).upper().strip()
    r = TR.get(s, TR.get("_GLOBAL", {}))
    v = r.get("U")
    return float(v) if v and not np.isnan(float(v)) else float(TR["_GLOBAL"]["U"])
def ter_N(section):
    s = str(section).upper().strip()
    r = TR.get(s, TR.get("_GLOBAL", {}))
    v = r.get("N", 52.)
    return float(v) if v and not np.isnan(float(v)) else 52.

# ── make_xgb ──────────────────────────────────────────────────────────────────
def make_xgb(n=700):
    return XGBRegressor(n_estimators=n, max_depth=5, learning_rate=0.08,
        subsample=0.85, colsample_bytree=0.85, reg_alpha=0.3, reg_lambda=1.5,
        min_child_weight=4, random_state=42, n_jobs=-1, verbosity=0)

# ── pre_terrain : ajoute _tu _tn surf_U surf_N surf_ERR ──────────────────────
def pre_terrain(df_in):
    ptz_ = df_in["plu_typezone"].fillna("ERR").values
    sec_ = df_in["section"].fillna("_GLOBAL").values
    df_in["_tu"]     = np.array([ter_U(s) for s in sec_])
    df_in["_tn"]     = np.array([ter_N(s) for s in sec_])
    df_in["surf_U"]  = np.where(np.isin(ptz_, ["U","AU","AUc"]), df_in["surf_terrain"], 0.)
    df_in["surf_N"]  = np.where(np.isin(ptz_, ["N","A","HORS","Ah"]), df_in["surf_terrain"], 0.)
    df_in["surf_ERR"]= np.where(ptz_=="ERR", df_in["surf_terrain"], 0.)
    return df_in

# ── build_X : construit la matrice de features ────────────────────────────────
def build_X(df_in, section_te_map=None):
    f = {}
    ptz_in = df_in["plu_typezone"].fillna("ERR").values
    def sn(c, fb=0.):
        return df_in[c].fillna(fb).values if c in df_in.columns else np.full(len(df_in), fb)

    # Section target encoding
    mean_g  = df_in["prix_m2"].mean() if section_te_map is None else np.mean(list(section_te_map.values()))
    ste_map = section_te_map if section_te_map is not None \
              else df_in.groupby("section")["prix_m2"].mean().to_dict()
    ste = df_in["section"].fillna("").map(ste_map).fillna(mean_g).values
    f["section_te"]     = ste
    f["log_section_te"] = np.log1p(ste)

    # Structurel
    f["surface"]      = sn("surface")
    f["surf_terrain"] = sn("surf_terrain")
    f["pieces"]       = sn("pieces", 4.)
    f["annee"]        = sn("annee", 2022.)
    f["annee_m2022"]  = f["annee"] - 2022
    f["log_surface"]  = np.log1p(f["surface"])
    f["log_terrain"]  = np.log1p(f["surf_terrain"])
    f["sqrt_terrain"] = np.sqrt(f["surf_terrain"])
    f["ratio_ter"]    = f["surf_terrain"] / (f["surface"] + 1)

    # PLU
    is_U  = (ptz_in=="U").astype(float)
    is_N  = (ptz_in=="N").astype(float)
    is_A  = np.array([1. if p in ("A","HORS","Ah") else 0. for p in ptz_in])
    is_AU = np.array([1. if p in ("AU","AUc") else 0. for p in ptz_in])
    is_ER = (ptz_in=="ERR").astype(float)
    f["plu_is_U"]=is_U; f["plu_is_N"]=is_N; f["plu_is_A"]=is_A
    f["plu_is_AU"]=is_AU; f["plu_is_ERR"]=is_ER

    # Valeurs monetaires
    tu_v      = df_in["_tu"].values
    tn_v      = df_in["_tn"].values
    surf_U_v  = df_in["surf_U"].values
    surf_N_v  = df_in["surf_N"].values
    surf_ER_v = df_in["surf_ERR"].values

    f["val_bati"]         = f["surface"] * ste
    f["val_ter_U"]        = surf_U_v  * tu_v
    f["val_ter_N"]        = surf_N_v  * tn_v
    f["val_ter_ERR"]      = surf_ER_v * tu_v * 0.5
    f["val_terrain"]      = f["val_ter_U"] + f["val_ter_N"] + f["val_ter_ERR"]
    f["val_total_est"]    = f["val_bati"] + f["val_terrain"]
    f["val_ter_per_bati"] = f["val_terrain"] / (f["surface"] + 1)

    f["log_val_bati"]    = np.log1p(f["val_bati"])
    f["log_val_terrain"] = np.log1p(f["val_terrain"])
    f["log_val_ter_U"]   = np.log1p(f["val_ter_U"])
    f["log_val_total"]   = np.log1p(f["val_total_est"])
    f["surf_composite"]  = f["surface"] + surf_U_v
    f["log_composite"]   = np.log1p(f["surf_composite"])

    # Localisation fine (données dvf_clean.csv)
    f["altitude"]        = sn("altitude", 1063.)       # médiane Chamonix
    f["dist_ski_lift"]   = sn("dist_ski_lift_km", 0.56)
    f["dist_centre"]     = sn("dist_centre_km", 2.16)
    f["log_alt"]         = np.log1p(f["altitude"])
    f["alt_rel"]         = f["altitude"] - 950.        # relatif fond vallée

    return pd.DataFrame(f).fillna(0)

# ── loy_market_evolution : Leave-One-Year-Out → index empirique ──────────────
def loy_market_evolution(df_clean, min_n=8):
    """
    Pour chaque année Y :
      - Entraîne sur toutes les autres années (features SANS signal année)
      - Prédit les biens de l'année Y
      - ratio = median(actual_Y) / median(pred_Y)
        = évolution de marché pure, composition-ajustée

    Pourquoi neutraliser l'année ?
      Si on laisse annee_m2022 dans les features, le modèle apprend déjà
      "2024 = +33%". Le ratio serait ~1.0 partout → signal nul.
      En forçant annee=2022 pour tous, on obtient le prix "hors tendance"
      basé sur les caractéristiques du bien uniquement.
      Le ratio réel/prédit = effet marché pur.
    """
    df_neutral = df_clean.copy()
    df_neutral["annee"] = 2022.     # neutralise annee_m2022 = 0 partout

    years = sorted(df_clean["annee"].dropna().unique())
    results = []

    print(f"\n=== Leave-One-Year-Out — évolution marché empirique ===")
    for yr in years:
        mask_yr   = df_clean["annee"] == yr
        train_idx = df_clean[~mask_yr].index
        test_idx  = df_clean[ mask_yr].index

        n_test  = mask_yr.sum()
        n_train = (~mask_yr).sum()

        if n_test < min_n or n_train < 40:
            print(f"  LOY {int(yr)}: skip  (test={n_test}, train={n_train})")
            continue

        tr = df_neutral.loc[train_idx].copy()
        te = df_neutral.loc[test_idx ].copy()
        pre_terrain(tr); pre_terrain(te)

        # section_te sur prix_m2 brut (pas normalisé — l'année est neutralisée)
        ste_loy = tr.groupby("section")["prix_m2"].mean().to_dict()

        X_tr = build_X(tr, ste_loy)
        X_te = build_X(te, ste_loy)

        # Cible : log(valeur brute) — pas de normalisation externe
        y_tr = np.log(df_clean.loc[train_idx, "valeur"].clip(50_000, 50_000_000))

        m = make_xgb(600)
        m.fit(X_tr, y_tr.values)
        pred = np.exp(m.predict(X_te))

        actual    = df_clean.loc[test_idx, "valeur"].values
        ratio     = float(np.median(actual) / np.median(pred))
        mape_loy  = float(np.mean(np.abs(actual - pred) / actual) * 100)
        bias_pct  = (np.median(actual) - np.median(pred)) / np.median(pred) * 100

        results.append({
            "annee":      int(yr),
            "n":          int(n_test),
            "ratio_raw":  ratio,
            "actual_med": float(np.median(actual)),
            "pred_med":   float(np.median(pred)),
            "mape":       mape_loy,
            "bias_pct":   bias_pct,
        })
        print(f"  LOY {int(yr)} n={n_test:>2}: "
              f"actual={np.median(actual)/1e6:.3f}M€  "
              f"pred={np.median(pred)/1e6:.3f}M€  "
              f"ratio={ratio:.3f}  biais={bias_pct:+.1f}%  MAPE={mape_loy:.1f}%")

    # Normaliser : l'année de référence 2022 → 1.000
    ref_r = next((r["ratio_raw"] for r in results if r["annee"] == 2022), None)
    if ref_r is None:
        ref_r = float(np.median([r["ratio_raw"] for r in results]))
        print(f"  (2022 absent, normalisation sur médiane={ref_r:.3f})")

    for r in results:
        r["idx_empirique"] = round(r["ratio_raw"] / ref_r, 4)

    emp_idx = {r["annee"]: r["idx_empirique"] for r in results}
    print(f"\n  Index empirique (ref 2022=1.000):")
    for yr, idx in sorted(emp_idx.items()):
        naive = MARKET_INDEX.get(yr, float("nan"))
        diff  = (idx - naive) / naive * 100 if not np.isnan(naive) else float("nan")
        print(f"    {int(yr)}: empirique={idx:.3f}  naïf={naive:.3f}  diff={diff:+.1f}%")

    return results, emp_idx

# ── oof_residuals : résidus OOF honnetes (cible log valeur_norm) ─────────────
def oof_residuals(df_in, n_splits=5):
    df_in = df_in.reset_index(drop=True)
    pre_terrain(df_in)
    # Recalc valeur_norm si pas dispo (appelé pendant le nettoyage itératif)
    if "valeur_norm" not in df_in.columns:
        df_in["market_idx"]  = df_in["annee"].map(MARKET_INDEX).fillna(1.0)
        df_in["valeur_norm"] = df_in["valeur"] / df_in["market_idx"]
        df_in["prix_m2_norm"]= df_in["prix_m2"] / df_in["market_idx"]
    y     = np.log(df_in["valeur_norm"].clip(50_000, 50_000_000))
    y_oof = np.zeros(len(df_in))
    kf    = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    for tr_idx, va_idx in kf.split(np.arange(len(df_in))):
        tr = df_in.iloc[tr_idx]; va = df_in.iloc[va_idx]
        # section_te sur prix_m2 normalisé → comparable cross-années
        ste = tr.groupby("section")["prix_m2_norm"].mean().to_dict()
        Xtr = build_X(tr, ste); Xva = build_X(va, ste)
        m   = make_xgb()
        m.fit(Xtr, y.values[tr_idx])
        y_oof[va_idx] = m.predict(Xva)
    # Dénormaliser pour err_pct en valeur réelle
    pred_norm = np.exp(y_oof)
    pred_val  = pred_norm * df_in["market_idx"].values
    err_pct   = (df_in["valeur"].values - pred_val) / pred_val * 100
    r2        = 1 - np.sum((y-y_oof)**2) / np.sum((y-y.mean())**2)
    return err_pct, r2

# ── impute_plu_err : ERR = timeout API → impute N si prix << médiane U section
def impute_plu_err(df_in):
    """Remplace plu_typezone='ERR' par 'N' si prix/m² < 70% médiane U de la section."""
    df_in = df_in.copy()
    med_U = df_in[df_in["plu_typezone"]=="U"].groupby("section")["prix_m2"].median()
    err_mask = df_in["plu_typezone"].fillna("ERR") == "ERR"
    n_fixed = 0
    for idx in df_in[err_mask].index:
        sec = df_in.at[idx, "section"]
        p   = df_in.at[idx, "prix_m2"]
        mu  = med_U.get(sec, np.nan)
        if np.isnan(mu) or p < mu * 0.70:
            df_in.at[idx, "plu_typezone"] = "N"
            n_fixed += 1
    print(f"  Imputation ERR→N : {n_fixed} / {err_mask.sum()} transactions ERR corrigées")
    return df_in

# ══════════════════════════════════════════════════════════════════════════════
# CHARGEMENT DONNEES
# ══════════════════════════════════════════════════════════════════════════════
df_raw = pd.read_csv(os.path.join(DVF_DIR, "dvf_clean.csv"), low_memory=False)
for c in ["prix_m2","valeur","surface","surf_terrain","pieces","annee","mois","plu_enc",
          "has_parking","n_dependances","nb_lots","dist_centre_km","dist_ski_lift_km",
          "altitude","lat","lon"]:
    if c in df_raw.columns: df_raw[c] = pd.to_numeric(df_raw[c], errors="coerce")
df_raw["surf_terrain"] = df_raw["surf_terrain"].fillna(0)
df_raw["valeur"]       = df_raw["valeur"].fillna(0)

# ── Index marché annuel (maisons Chamonix, référence 2022) ───────────────────
_ch_all = df_raw[
    (df_raw["commune"]=="CHAMONIX MONT BLANC") &
    (df_raw["type_local"]=="maison")
].dropna(subset=["prix_m2","annee"]).copy()
_ch_all = _ch_all[_ch_all["prix_m2"].between(1000, 60000)]
_idx_raw = _ch_all.groupby("annee")["prix_m2"].agg(["median","count"])
_idx_raw = _idx_raw[_idx_raw["count"] >= 5]
_ref2022 = _idx_raw.loc[2022, "median"]
MARKET_INDEX = (_idx_raw["median"] / _ref2022).to_dict()   # {2021:0.865, 2022:1.0, ...}
MARKET_INDEX_CURRENT = MARKET_INDEX.get(2025, MARKET_INDEX.get(2024, 1.0))
print("Index marché annuel Chamonix (maisons, ref=2022) :")
for yr, idx in sorted(MARKET_INDEX.items()):
    print(f"  {int(yr)}: {idx:.3f}")
json.dump({int(k): round(v,4) for k,v in MARKET_INDEX.items()},
          open(os.path.join(DVF_DIR,"market_index.json"),"w"))

df = df_raw[
    (df_raw["commune"]=="CHAMONIX MONT BLANC") &
    (df_raw["type_local"]=="maison")
].dropna(subset=["prix_m2","valeur","surface"]).copy().reset_index(drop=True)
print(f"\nBrut Chamonix: {len(df)} maisons")

# Normaliser valeur par index annuel → "euros constants 2022"
df["market_idx"] = df["annee"].map(MARKET_INDEX).fillna(1.0)
df["valeur_norm"] = df["valeur"] / df["market_idx"]
df["prix_m2_norm"]= df["prix_m2"] / df["market_idx"]

# Imputation PLU ERR (timeouts API → N si prix << médiane U section)
df = impute_plu_err(df)
n_err_left = (df["plu_typezone"].fillna("ERR")=="ERR").sum()
print(f"  ERR restants après imputation : {n_err_left}")

# ══════════════════════════════════════════════════════════════════════════════
# NETTOYAGE PASSE 1 — composite ±50%/+100% par section
# ══════════════════════════════════════════════════════════════════════════════
ptz = df["plu_typezone"].fillna("ERR").values
df["surf_constructible"] = np.where(np.isin(ptz,["U","AU","AUc"]), df["surf_terrain"], 0.)
df["surf_composite"]     = df["surface"] + df["surf_constructible"]
df["prix_composite"]     = df["valeur"] / df["surf_composite"].clip(1)

kept = []
print("\nPasse 1 — composite ±50%/+100% par section:")
for sec_key, g in df.groupby("section"):
    med = g["prix_composite"].median()
    lo, hi = med * 0.5, med * 2.0
    mask = (g["prix_composite"] >= lo) & (g["prix_composite"] <= hi)
    kept.append(g[mask])
    print(f"  Section {sec_key}  n={len(g):>3}  med={med:>6,.0f}  "
          f"[{lo:>6,.0f}-{hi:>6,.0f}]  retire={int((~mask).sum())}")

df = pd.concat(kept).reset_index(drop=True)
print(f"  → {len(df)} transactions après passe 1")

# ══════════════════════════════════════════════════════════════════════════════
# NETTOYAGE PASSES 2-4 — résidus OOF itératifs
# ══════════════════════════════════════════════════════════════════════════════
ITER_THRESH = [60, 50, 45]

print(f"\nNettoyage itératif par résidus OOF (cible = valeur totale):")
for it, thresh in enumerate(ITER_THRESH, 2):
    err_iter, r2_iter = oof_residuals(df)
    outliers  = np.abs(err_iter) > thresh
    n_rm      = outliers.sum()
    mape_iter = np.mean(np.abs(err_iter))
    print(f"\n  Passe {it}  seuil |err|>{thresh}%  →  R²={r2_iter:.3f}  MAPE={mape_iter:.1f}%  retire={n_rm}")
    if n_rm > 0:
        for i in np.where(outliers)[0]:
            row = df.iloc[i]
            voie_s = str(row.get("voie","") if "voie" in df.columns else "")
            print(f"    ✂ {voie_s:<38}  sec={row['section']}  PLU={row['plu_typezone']}"
                  f"  val={row['valeur']:>9,.0f}€  err={err_iter[i]:+.0f}%")
    df = df[~outliers].reset_index(drop=True)
    print(f"  → {len(df)} transactions restantes")

print(f"\nDataset final: {len(df)} transactions")
print(f"  valeur : {df['valeur'].min()/1e6:.2f} - {df['valeur'].max()/1e6:.2f} M€  "
      f"med={df['valeur'].median()/1e6:.2f} M€")
print(f"  prix_m2: {df['prix_m2'].min():.0f} - {df['prix_m2'].max():.0f}  "
      f"med={df['prix_m2'].median():.0f}")
print(f"  Sections: {df['section'].value_counts().to_dict()}")

# ══════════════════════════════════════════════════════════════════════════════
# LEAVE-ONE-YEAR-OUT — index empirique composition-ajusté
# ══════════════════════════════════════════════════════════════════════════════
LOY_RESULTS, EMPIRICAL_INDEX = loy_market_evolution(df)
# Sauvegarde index empirique
json.dump(
    {str(int(k)): round(float(v), 4) for k, v in EMPIRICAL_INDEX.items()},
    open(os.path.join(DVF_DIR, "empirical_market_index.json"), "w"), indent=2
)
print(f"\nIndex empirique sauvé → dvf/empirical_market_index.json")

# Index courant = dernière année avec n >= 10, en favorisant l'empirique
EMP_IDX_CURRENT = EMPIRICAL_INDEX.get(
    2024, EMPIRICAL_INDEX.get(2023, MARKET_INDEX_CURRENT)
)
print(f"Index courant (empirique): {EMP_IDX_CURRENT:.3f}  vs naïf: {MARKET_INDEX_CURRENT:.3f}")

# ══════════════════════════════════════════════════════════════════════════════
# CV FINAL 5-FOLD
# ══════════════════════════════════════════════════════════════════════════════
pre_terrain(df)
KF    = KFold(n_splits=5, shuffle=True, random_state=42)
# Cible : log(valeur normalisée) → retire la tendance temporelle
y_all = np.log(df["valeur_norm"].clip(50_000, 50_000_000))
y_oof = np.zeros(len(df))
fold_r2 = []

print("\n=== CV final 5-fold (cible = log valeur normalisée) ===")
for fold, (tr_idx, va_idx) in enumerate(KF.split(np.arange(len(df))), 1):
    tr = df.iloc[tr_idx]; va = df.iloc[va_idx]
    # section_te sur prix_m2 normalisé
    ste_fold = tr.groupby("section")["prix_m2_norm"].mean().to_dict()
    Xtr = build_X(tr, ste_fold); Xva = build_X(va, ste_fold)
    m   = make_xgb()
    m.fit(Xtr, y_all.values[tr_idx])
    y_oof[va_idx] = m.predict(Xva)
    r2 = 1 - np.sum((y_all.values[va_idx]-y_oof[va_idx])**2) / \
             np.sum((y_all.values[va_idx]-y_all.values[va_idx].mean())**2)
    fold_r2.append(r2)
    print(f"  Fold {fold}: R²={r2:.4f}  n={len(va_idx)}")

r2_oof     = 1 - np.sum((y_all-y_oof)**2) / np.sum((y_all-y_all.mean())**2)
actual_val = df["valeur"].values
# Dénormaliser : prédiction en valeur réelle (euros courants de l'année)
pred_val   = np.exp(y_oof) * df["market_idx"].values
err_pct    = (actual_val - pred_val) / pred_val * 100
mape       = np.mean(np.abs(actual_val - pred_val) / actual_val) * 100
mae_val    = np.mean(np.abs(actual_val - pred_val))
pct_25     = (np.abs(err_pct) <= 25).mean() * 100

print(f"\nR² OOF = {r2_oof:.4f}  folds {np.mean(fold_r2):.4f}±{np.std(fold_r2):.4f}")
print(f"MAPE={mape:.1f}%  MAE={mae_val/1000:,.0f} k€  {pct_25:.0f}% dans ±25%")

# Feature importances (fit final sur valeur_norm)
ste_global = df.groupby("section")["prix_m2_norm"].mean().to_dict()
X_all  = build_X(df, ste_global)
m_final = make_xgb(800)
m_final.fit(X_all, y_all)
imp     = pd.Series(m_final.get_booster().get_score(importance_type="gain"))
imp_pct = (imp / imp.sum() * 100).sort_values(ascending=False)

FEAT_LABELS = {
    "section_te":"Section (prix med.)", "log_section_te":"log(Section)",
    "plu_is_U":"PLU zone U", "plu_is_ERR":"PLU inconnu", "plu_is_N":"PLU zone N",
    "val_ter_per_bati":"Prime terrain / m² bâti",
    "val_ter_U":"Valeur terrain zone U", "val_ter_ERR":"Valeur terrain ERR",
    "val_bati":"Valeur bâtie", "val_terrain":"Valeur terrain totale",
    "log_val_bati":"log(val. bâtie)", "log_val_terrain":"log(val. terrain)",
    "log_val_ter_U":"log(val. terrain U)",
    "val_total_est":"Valeur totale estimée", "log_val_total":"log(val. totale)",
    "surf_composite":"Surf. composite", "log_composite":"log(surf. composite)",
    "surface":"Surface bâtie", "log_surface":"log(surface)",
    "surf_terrain":"Surf. terrain", "sqrt_terrain":"sqrt(terrain)",
    "ratio_ter":"Ratio terrain/bâti", "pieces":"Pièces",
    "annee_m2022":"Année (delta)", "plu_is_A":"PLU zone A",
    "altitude":"Altitude (m)", "log_alt":"log(altitude)", "alt_rel":"Altitude rel. vallée",
    "dist_ski_lift":"Dist. remontée (km)", "dist_centre":"Dist. centre (km)",
}
print("\nTop features (gain):")
for k, v in imp_pct.head(12).items():
    print(f"  {FEAT_LABELS.get(k,k):<32} {v:.1f}%")

print("\nStats par section:")
for sec, g in df.groupby("section"):
    idx_s = g.index.tolist()
    er = err_pct[idx_s]
    denom = np.sum((y_all.values[idx_s]-y_all.values[idx_s].mean())**2) + 1e-9
    r2_s  = 1 - np.sum((y_all.values[idx_s]-y_oof[idx_s])**2) / denom
    print(f"  Section {sec}  n={len(g):>3}  med_val={g['valeur'].median()/1e6:.2f}M€"
          f"  MAPE={np.mean(np.abs(er)):.1f}%  R²={r2_s:.3f}")

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD 5 PANNEAUX
# ══════════════════════════════════════════════════════════════════════════════
av_M = actual_val / 1e6
pv_M = pred_val   / 1e6
pm2  = df["prix_m2"].values
secs_ord = sorted(df["section"].unique())

fig = make_subplots(
    rows=4, cols=2,
    row_heights=[0.38, 0.22, 0.22, 0.18],
    vertical_spacing=0.07, horizontal_spacing=0.08,
    subplot_titles=[
        "Valeur réelle vs Valeur modèle OOF  (taille = terrain · couleur = section)",
        "",
        "Importances features (gain XGBoost)",
        "Distribution résidus % sur valeur totale",
        "Prime terrain / m² bâti  vs  Valeur réelle",
        "Valeur modèle OOF  vs  Valeur réelle  (couleur = résidu %)",
        "Évolution marché  —  Index empirique LOY vs Index naïf (médiane brute)",
        "",
    ],
    specs=[[{"type":"scatter","colspan":2}, None],
           [{"type":"bar"},               {"type":"histogram"}],
           [{"type":"scatter"},           {"type":"scatter"}],
           [{"type":"scatter","colspan":2}, None]],
)

# ── 1. Scatter principal valeur totale ───────────────────────────────────────
lim_lo = min(av_M.min(), pv_M.min()) * 0.88
lim_hi = max(av_M.max(), pv_M.max()) * 1.06
fig.add_trace(go.Scatter(x=[lim_lo,lim_hi], y=[lim_lo,lim_hi],
    mode="lines", showlegend=False, hoverinfo="skip",
    line=dict(color="#334155",width=1.5,dash="dot")), row=1,col=1)
for pct_l, col_l, nm in [(-25,"#dc2626","-25%"),(+25,"#16a34a","+25%")]:
    fig.add_trace(go.Scatter(x=[lim_lo,lim_hi],
        y=[lim_lo*(1+pct_l/100), lim_hi*(1+pct_l/100)],
        mode="lines", name=nm, hoverinfo="skip",
        line=dict(color=col_l,width=1,dash="dash")), row=1,col=1)

for sec in secs_ord:
    mask_s = df["section"]==sec
    idx_s  = df[mask_s].index.tolist()
    av_s   = av_M[idx_s]; pv_s=pv_M[idx_s]; e_s=err_pct[idx_s]
    ter    = df.loc[idx_s,"surf_terrain"].fillna(0).values
    sz     = 8 + np.sqrt(np.clip(ter,0,5000)/5000) * 24
    hover  = [
        f"<b>{df.loc[i,'voie'] if 'voie' in df.columns else ''}</b>  —  Section {sec}<br>"
        f"Réel <b>{av_s[j]:.3f} M€</b>  →  modèle <b>{pv_s[j]:.3f} M€</b>"
        f"  (<b style='color:{'#ef4444' if e_s[j]<-20 else '#22c55e' if e_s[j]>20 else '#94a3b8'}'>"
        f"{e_s[j]:+.0f}%</b>)<br>"
        f"Surf {df.loc[i,'surface']:.0f} m²  ·  Terrain {ter[j]:.0f} m²  ·  PLU {df.loc[i,'plu_typezone']}<br>"
        f"{df.loc[i,'prix_m2']:,.0f} €/m²  ·  {int(df.loc[i,'annee'])}"
        "<extra></extra>"
        for j,i in enumerate(idx_s)
    ]
    fig.add_trace(go.Scatter(
        x=av_s, y=pv_s, mode="markers",
        name=f"Section {sec} (n={mask_s.sum()})",
        marker=dict(color=SEC_COLOR.get(sec,"#94a3b8"), size=sz, opacity=0.85,
                    line=dict(width=0.8,color="#0f172a")),
        hovertemplate=hover,
    ), row=1,col=1)

fig.add_annotation(x=0.01, y=0.98, xref="x domain", yref="y domain",
    text=(f"<b>R² = {r2_oof:.3f}</b>  ·  folds {np.mean(fold_r2):.3f}±{np.std(fold_r2):.3f}"
          f"<br>MAPE = {mape:.1f}%  ·  MAE = {mae_val/1000:,.0f} k€"
          f"<br>n = {len(df)} maisons  ·  {pct_25:.0f}% dans ±25%"),
    showarrow=False, align="left", font=dict(size=12,color=TXT),
    bgcolor="#1a1d27", bordercolor="#3d4266", borderwidth=1)

# ── 2. Feature importances ───────────────────────────────────────────────────
top12 = imp_pct.head(12)
labs  = [FEAT_LABELS.get(k,k) for k in top12.index[::-1]]
vals  = top12.values[::-1]
cmap  = ["#ef4444","#f97316","#f59e0b","#eab308","#84cc16","#22c55e",
         "#10b981","#06b6d4","#3b82f6","#8b5cf6","#a855f7","#ec4899"][::-1]
fig.add_trace(go.Bar(
    x=vals, y=labs, orientation="h", showlegend=False,
    marker_color=cmap,
    text=[f"{v:.1f}%" for v in vals], textposition="outside",
    textfont=dict(size=10,color=TXT),
    hovertemplate="%{y}: %{x:.2f}%<extra></extra>",
), row=2,col=1)

# ── 3. Histogramme résidus ───────────────────────────────────────────────────
for sec in secs_ord:
    mask_s = df["section"]==sec
    fig.add_trace(go.Histogram(
        x=err_pct[df[mask_s].index.tolist()],
        xbins=dict(start=-60,end=80,size=5),
        name=f"Section {sec}", showlegend=False,
        marker_color=SEC_COLOR.get(sec,"#94a3b8"), opacity=0.65,
    ), row=2,col=2)
fig.add_vline(x=0,   line_dash="solid", line_color="#64748b", line_width=1, row=2,col=2)
fig.add_vline(x=25,  line_dash="dash",  line_color="#16a34a", line_width=1, row=2,col=2)
fig.add_vline(x=-25, line_dash="dash",  line_color="#dc2626", line_width=1, row=2,col=2)
fig.add_annotation(x=60, y=0.92, xref="x4", yref="y4 domain",
    text=f"{(np.abs(err_pct)>25).mean()*100:.0f}%<br>hors ±25%",
    font=dict(color=TXT,size=10), bgcolor="#1a1d27",
    bordercolor="#475569", borderwidth=1, showarrow=False)

# ── 4. Prime terrain vs valeur réelle ────────────────────────────────────────
val_tp = X_all["val_ter_per_bati"].values
for sec in secs_ord:
    mask_s = df["section"]==sec
    idx_s  = df[mask_s].index.tolist()
    ptz_s  = df.loc[idx_s,"plu_typezone"].fillna("ERR").values
    sz_s   = 7 + np.sqrt(np.clip(df.loc[idx_s,"surf_terrain"].fillna(0).values,0,5000)/5000)*18
    fig.add_trace(go.Scatter(
        x=val_tp[idx_s], y=av_M[idx_s], mode="markers",
        name=f"Section {sec}", showlegend=False,
        marker=dict(color=SEC_COLOR.get(sec,"#94a3b8"),
                    symbol=["circle" if p=="U" else "cross" if p=="N" else "diamond" for p in ptz_s],
                    size=sz_s, opacity=0.78, line=dict(width=0.5,color="#0f172a")),
        hovertemplate=(f"Section {sec}  PLU:%{{customdata}}<br>"
                       f"Prime terrain/m² bâti: %{{x:,.0f}} €<br>"
                       f"Valeur réelle: %{{y:.3f}} M€<extra></extra>"),
        customdata=ptz_s,
    ), row=3,col=1)

# ── 5. pred_val OOF vs valeur réelle (centré sur diagonale) ──────────────────
lv_lo = min(pv_M.min(), av_M.min()) * 0.85
lv_hi = max(pv_M.max(), av_M.max()) * 1.08
# ligne 1:1
fig.add_trace(go.Scatter(x=[lv_lo,lv_hi], y=[lv_lo,lv_hi],
    mode="lines", showlegend=False, hoverinfo="skip",
    line=dict(color="#334155",width=1.5,dash="dot")), row=3,col=2)
# bandes ±25%
for pct_l, col_l in [(-25,"#dc2626"),(+25,"#16a34a")]:
    fig.add_trace(go.Scatter(x=[lv_lo,lv_hi],
        y=[lv_lo*(1+pct_l/100), lv_hi*(1+pct_l/100)],
        mode="lines", showlegend=False, hoverinfo="skip",
        line=dict(color=col_l,width=1,dash="dash")), row=3,col=2)

# scatter coloré par résidu % (rouge=sous-estimé, vert=sur-estimé, blanc=ok)
fig.add_trace(go.Scatter(
    x=pv_M, y=av_M, mode="markers",
    showlegend=False,
    marker=dict(
        color=err_pct,
        colorscale=[[0,"#dc2626"],[0.35,"#f97316"],[0.5,"#e2e8f0"],[0.65,"#60a5fa"],[1,"#7c3aed"]],
        cmin=-50, cmax=50,
        size=7 + np.sqrt(np.clip(df["surf_terrain"].fillna(0).values,0,5000)/5000)*16,
        opacity=0.85,
        showscale=True,
        colorbar=dict(
            title=dict(text="résidu %",font=dict(color=TXT,size=10)),
            tickfont=dict(color=TXT,size=9),
            ticksuffix="%", len=0.28, y=0.08,
            tickvals=[-50,-25,0,25,50],
            ticktext=["-50%","-25%","0","+25%","+50%"],
        ),
        line=dict(width=0.5,color="#0f172a"),
    ),
    customdata=np.stack([
        df["section"].values,
        df["prix_m2"].values,
        df["surface"].values,
        df["surf_terrain"].fillna(0).values,
        df["plu_typezone"].fillna("?").values,
        err_pct,
    ], axis=1),
    hovertemplate=(
        "<b>%{customdata[0]}</b>  PLU %{customdata[4]}<br>"
        "Modèle <b>%{x:.3f} M€</b>  ·  Réel <b>%{y:.3f} M€</b><br>"
        "Résidu <b>%{customdata[5]:+.0f}%</b><br>"
        "Surf %{customdata[2]:.0f}m²  ·  Terrain %{customdata[3]:.0f}m²  ·  "
        "%{customdata[1]:,.0f} €/m²"
        "<extra></extra>"
    ),
), row=3,col=2)

# ── 6. Panel LOY : index empirique vs naïf ───────────────────────────────────
loy_yrs       = sorted(EMPIRICAL_INDEX.keys())
loy_emp_vals  = [EMPIRICAL_INDEX[y]        for y in loy_yrs]
loy_naive_vals= [MARKET_INDEX.get(y, None) for y in loy_yrs]

# Ligne index empirique
fig.add_trace(go.Scatter(
    x=loy_yrs, y=loy_emp_vals, mode="lines+markers",
    name="Index empirique LOY",
    line=dict(color="#34d399", width=2.5),
    marker=dict(size=9, color="#34d399", line=dict(width=1.5, color="#0f172a")),
    hovertemplate="<b>%{x}</b>  empirique=%{y:.3f}<extra></extra>",
), row=4, col=1)

# Ligne index naïf (médiane brute)
fig.add_trace(go.Scatter(
    x=loy_yrs, y=loy_naive_vals, mode="lines+markers",
    name="Index naïf (médiane brute)",
    line=dict(color="#f97316", width=2, dash="dash"),
    marker=dict(size=7, color="#f97316"),
    hovertemplate="<b>%{x}</b>  naïf=%{y:.3f}<extra></extra>",
), row=4, col=1)

# Bulles taille = n transactions
loy_n_vals = [next((r["n"] for r in LOY_RESULTS if r["annee"] == y), 0) for y in loy_yrs]
fig.add_trace(go.Scatter(
    x=loy_yrs, y=loy_emp_vals, mode="markers",
    showlegend=False,
    marker=dict(
        size=[6 + n * 0.9 for n in loy_n_vals],
        color="#34d399", opacity=0.25,
        line=dict(width=0),
    ),
    hovertemplate=[
        f"<b>{y}</b>  n={n}  biais={next((r['bias_pct'] for r in LOY_RESULTS if r['annee']==y), 0):+.1f}%"
        "<extra></extra>"
        for y, n in zip(loy_yrs, loy_n_vals)
    ],
), row=4, col=1)

# Ligne de référence 2022=1.0
fig.add_hline(y=1.0, line_dash="dot", line_color="#334155", line_width=1.5, row=4, col=1)

# Annotation delta final (empirique vs naïf, dernière année commune)
last_yr = max(y for y in loy_yrs if MARKET_INDEX.get(y) is not None)
delta   = EMPIRICAL_INDEX.get(last_yr, 0) - MARKET_INDEX.get(last_yr, 0)
fig.add_annotation(
    x=0.98, y=0.92, xref="x7 domain", yref="y7 domain",
    text=(f"<b>{int(last_yr)}</b>  empirique={EMPIRICAL_INDEX.get(last_yr,0):.3f}"
          f"  naïf={MARKET_INDEX.get(last_yr,0):.3f}"
          f"  Δ={delta:+.3f}"),
    showarrow=False, align="right",
    font=dict(size=11, color=TXT),
    bgcolor="#1a1d27", bordercolor="#3d4266", borderwidth=1,
)

# ── Layout ───────────────────────────────────────────────────────────────────
AXIS = dict(gridcolor=GRID, zerolinecolor=GRID, color=TXT,
            title_font=dict(color=TXT,size=11), tickfont=dict(color=TXT,size=10))

fig.update_layout(
    title=dict(
        text=(f"<b>Chamonix — AVM v2  ·  cible = valeur normalisée (index marché annuel)</b>"
              f"  ·  n={len(df)}  ·  R² = {r2_oof:.3f}  ·  MAPE = {mape:.1f}%"
              f"<br><sup>Nettoyage composite + résidus OOF  ·  "
              f"section_te normalisé  ·  +altitude +dist_ski  ·  CV 5-fold</sup>"),
        font=dict(size=13,color=TXT), x=0.5,
    ),
    paper_bgcolor=BG, plot_bgcolor=PBG, font=dict(color=TXT,family="system-ui"),
    barmode="overlay",
    legend=dict(bgcolor="#1a1d27",bordercolor="#2d3148",borderwidth=1,
                font=dict(size=11),orientation="h",x=0.5,xanchor="center",y=-0.03),
    hoverlabel=dict(bgcolor="#1a1d27",bordercolor="#4f8ef7",font=dict(size=12,color=TXT)),
    hovermode="closest", width=1500, height=2100,
    margin=dict(l=60,r=60,t=100,b=70),
)
for r, c in [(1,1),(2,1),(2,2),(3,1),(3,2),(4,1)]:
    fig.update_xaxes(row=r, col=c, **AXIS, showgrid=True, gridwidth=1)
    fig.update_yaxes(row=r, col=c, **AXIS, showgrid=True, gridwidth=1)

fig.update_xaxes(row=1,col=1,title="Valeur réelle (M€)",    tickformat=".2f",ticksuffix=" M€")
fig.update_yaxes(row=1,col=1,title="Valeur modèle OOF (M€)",tickformat=".2f",ticksuffix=" M€")
fig.update_xaxes(row=2,col=1,title="Gain %",                ticksuffix="%")
fig.update_yaxes(row=2,col=1,title="")
fig.update_xaxes(row=2,col=2,title="Écart % (valeur totale)",ticksuffix="%")
fig.update_yaxes(row=2,col=2,title="Nb transactions")
fig.update_xaxes(row=3,col=1,title="Prime terrain / m² bâti (€)",tickformat=",.0f",ticksuffix=" €")
fig.update_yaxes(row=3,col=1,title="Valeur réelle (M€)",    tickformat=".2f",ticksuffix=" M€")
fig.update_xaxes(row=3,col=2,title="Valeur modèle OOF (M€)",tickformat=".2f",ticksuffix=" M€")
fig.update_yaxes(row=3,col=2,title="Valeur réelle (M€)",    tickformat=".2f",ticksuffix=" M€")
fig.update_xaxes(row=4,col=1,title="Année",                 dtick=1, tickformat="d")
fig.update_yaxes(row=4,col=1,title="Index (ref 2022=1.000)",tickformat=".3f")

out = os.path.join(DVF_DIR, "chamonix_avm.html")
fig.write_html(out, include_plotlyjs="cdn")
print(f"\nExport → {out}")
print("DONE")
