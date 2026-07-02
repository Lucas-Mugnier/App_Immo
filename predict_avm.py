# -*- coding: utf-8 -*-
"""
predict_avm.py  —  Estimation AVM Chamonix (modele XGBoost DVF)
================================================================
USAGE :
    python predict_avm.py                 <- mode interactif
    python predict_avm.py G 75 660 U      <- args directs (section surface terrain PLU)
    python predict_avm.py G 75 660 U --prix 1800000   <- + score vs prix demande
    python predict_avm.py --retrain       <- forcer re-entrainement du modele

Le modele est entraine une seule fois depuis dvf/dvf_clean.csv puis cache
dans dvf/avm_model.pkl. Relance --retrain si tu ajoutes des donnees DVF.
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import argparse, json, os, warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

BASE         = Path(__file__).parent
DVF_DIR      = BASE / "dvf"
MODEL_PKL    = DVF_DIR / "avm_model.pkl"
ARTIFACTS    = DVF_DIR / "avm_artifacts.json"

# ── Defaults par section (altitude, distances) ─────────────────────────────
SECTION_DEFAULTS = {
    "A": {"altitude": 1391., "dist_centre": 9.502, "dist_ski": 1.245},
    "B": {"altitude": 1222., "dist_centre": 7.175, "dist_ski": 0.383},
    "C": {"altitude": 1076., "dist_centre": 2.760, "dist_ski": 0.641},
    "D": {"altitude": 1044., "dist_centre": 1.461, "dist_ski": 0.926},
    "E": {"altitude": 1032., "dist_centre": 3.247, "dist_ski": 0.565},
    "G": {"altitude": 1062., "dist_centre": 0.795, "dist_ski": 0.489},
}

# ── Terrain reference Chamonix (section x PLU) ────────────────────────────
def _load_terrain_ref():
    p = DVF_DIR / "terrain_ref_prix.json"
    if p.exists():
        return json.loads(p.read_text())
    # Fallback si fichier absent
    return {"_GLOBAL": {"U": 623., "N": 52.}}

def ter_U(section, tr):
    r = tr.get(section.upper(), tr.get("_GLOBAL", {}))
    v = r.get("U")
    return float(v) if v and not np.isnan(float(v)) else float(tr["_GLOBAL"]["U"])

def ter_N(section, tr):
    r = tr.get(section.upper(), tr.get("_GLOBAL", {}))
    v = r.get("N", 52.)
    return float(v) if v and not np.isnan(float(v)) else 52.

# ── Construction features (identique a chamonix_avm.py) ───────────────────
def build_features(section, surface, surf_terrain, plu_zone, pieces,
                   annee, altitude, dist_centre, dist_ski,
                   section_te_map, tr):
    """Construit le DataFrame de features pour une propriete."""
    sec  = section.upper()
    plu  = plu_zone.upper()

    # Section target encoding
    ste  = section_te_map.get(sec, np.mean(list(section_te_map.values())))

    # PLU flags
    is_U   = 1. if plu in ("U",)            else 0.
    is_N   = 1. if plu in ("N",)            else 0.
    is_A   = 1. if plu in ("A","HORS","AH") else 0.
    is_AU  = 1. if plu in ("AU","AUC")      else 0.
    is_ERR = 1. if plu in ("ERR","?","")    else 0.

    # Surfaces terrain par PLU
    surf_U   = surf_terrain if is_U  else 0.
    surf_N   = surf_terrain if is_N  else 0.
    surf_ERR = surf_terrain if is_ERR else 0.

    tu = ter_U(sec, tr)
    tn = ter_N(sec, tr)

    # Valeurs monetaires
    val_bati    = surface * ste
    val_ter_U   = surf_U   * tu
    val_ter_N   = surf_N   * tn
    val_ter_ERR = surf_ERR * tu * 0.5
    val_terrain = val_ter_U + val_ter_N + val_ter_ERR
    val_total   = val_bati  + val_terrain

    surf_composite = surface + surf_U

    f = {
        "section_te":       ste,
        "log_section_te":   np.log1p(ste),
        "surface":          surface,
        "surf_terrain":     surf_terrain,
        "pieces":           pieces,
        "annee":            float(annee),
        "annee_m2022":      float(annee) - 2022.,
        "log_surface":      np.log1p(surface),
        "log_terrain":      np.log1p(surf_terrain),
        "sqrt_terrain":     np.sqrt(surf_terrain),
        "ratio_ter":        surf_terrain / (surface + 1.),
        "plu_is_U":         is_U,
        "plu_is_N":         is_N,
        "plu_is_A":         is_A,
        "plu_is_AU":        is_AU,
        "plu_is_ERR":       is_ERR,
        "val_bati":         val_bati,
        "val_ter_U":        val_ter_U,
        "val_ter_N":        val_ter_N,
        "val_ter_ERR":      val_ter_ERR,
        "val_terrain":      val_terrain,
        "val_total_est":    val_total,
        "val_ter_per_bati": val_terrain / (surface + 1.),
        "log_val_bati":     np.log1p(val_bati),
        "log_val_terrain":  np.log1p(val_terrain),
        "log_val_ter_U":    np.log1p(val_ter_U),
        "log_val_total":    np.log1p(val_total),
        "surf_composite":   surf_composite,
        "log_composite":    np.log1p(surf_composite),
        "altitude":         altitude,
        "dist_ski_lift":    dist_ski,
        "dist_centre":      dist_centre,
        "log_alt":          np.log1p(altitude),
        "alt_rel":          altitude - 950.,
        "_tu":              tu,
        "_tn":              tn,
        "surf_U":           surf_U,
        "surf_N":           surf_N,
        "surf_ERR":         surf_ERR,
    }
    return pd.DataFrame([f])

# ── Entrainement ──────────────────────────────────────────────────────────
def train_and_save():
    from xgboost import XGBRegressor
    import joblib

    print("Chargement DVF...")
    df = pd.read_csv(DVF_DIR / "dvf_clean.csv", low_memory=False)
    for c in ["prix_m2","valeur","surface","surf_terrain","annee","pieces",
              "altitude","dist_centre_km","dist_ski_lift_km"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["surf_terrain"] = df["surf_terrain"].fillna(0)

    # Filtrer Chamonix maisons
    df = df[(df["commune"]=="CHAMONIX MONT BLANC") &
            (df["type_local"]=="maison")].dropna(
        subset=["prix_m2","valeur","surface","annee"]).reset_index(drop=True)
    df = df[df["prix_m2"].between(1000, 60_000)]
    print(f"  {len(df)} transactions Chamonix maisons")

    # Index marche annuel (ref 2022)
    idx_raw = df.groupby("annee")["prix_m2"].agg(["median","count"])
    idx_raw = idx_raw[idx_raw["count"] >= 5]
    ref2022 = idx_raw.loc[2022, "median"]
    mkt_idx = (idx_raw["median"] / ref2022).to_dict()
    df["market_idx"]   = df["annee"].map(mkt_idx).fillna(1.0)
    df["valeur_norm"]  = df["valeur"]  / df["market_idx"]
    df["prix_m2_norm"] = df["prix_m2"] / df["market_idx"]

    # Nettoyage composite basique (±50% / +100%)
    ptz = df["plu_typezone"].fillna("ERR").values
    df["surf_constructible"] = np.where(np.isin(ptz,["U","AU","AUc"]),df["surf_terrain"],0.)
    df["surf_composite"]     = df["surface"] + df["surf_constructible"]
    df["prix_composite"]     = df["valeur"] / df["surf_composite"].clip(1)
    kept = []
    for _, g in df.groupby("section"):
        med = g["prix_composite"].median()
        mask = (g["prix_composite"] >= med*0.5) & (g["prix_composite"] <= med*2.0)
        kept.append(g[mask])
    df = pd.concat(kept).reset_index(drop=True)
    print(f"  {len(df)} transactions apres nettoyage")

    # Section TE sur prix_m2 normalise
    ste_map = df.groupby("section")["prix_m2_norm"].mean().to_dict()
    tr      = _load_terrain_ref()

    # Construire matrice features
    rows = []
    for _, row in df.iterrows():
        sec = str(row.get("section","G")).upper()
        defs = SECTION_DEFAULTS.get(sec, SECTION_DEFAULTS["G"])
        X_row = build_features(
            section     = sec,
            surface     = float(row["surface"]),
            surf_terrain= float(row["surf_terrain"]),
            plu_zone    = str(row.get("plu_typezone","ERR") or "ERR"),
            pieces      = float(row.get("pieces") or max(1., float(row["surface"])/20.)),
            annee       = float(row["annee"]),
            altitude    = float(row["altitude"]) if pd.notna(row.get("altitude")) else defs["altitude"],
            dist_centre = float(row["dist_centre_km"]) if pd.notna(row.get("dist_centre_km")) else defs["dist_centre"],
            dist_ski    = float(row["dist_ski_lift_km"]) if pd.notna(row.get("dist_ski_lift_km")) else defs["dist_ski"],
            section_te_map = ste_map,
            tr             = tr,
        )
        rows.append(X_row)

    X_all = pd.concat(rows, ignore_index=True)
    y_all = np.log(df["valeur_norm"].clip(50_000, 50_000_000))

    # Entrainement XGBoost
    print("Entrainement XGBoost (800 arbres)...")
    model = XGBRegressor(n_estimators=800, max_depth=5, learning_rate=0.08,
        subsample=0.85, colsample_bytree=0.85, reg_alpha=0.3, reg_lambda=1.5,
        min_child_weight=4, random_state=42, n_jobs=-1, verbosity=0)
    model.fit(X_all, y_all)

    # ── Index marché : priorité empirique LOY, fallback médiane naïve ──────
    emp_path = DVF_DIR / "empirical_market_index.json"
    if emp_path.exists():
        emp_raw  = json.loads(emp_path.read_text())
        idx_used = {int(k): float(v) for k, v in emp_raw.items()}
        print("  Index marche : empirique LOY (composition-ajuste)")
    else:
        idx_used = mkt_idx
        print("  Index marche : median naif (lance chamonix_avm.py pour index LOY)")

    # Année de référence = dernière année avec au moins 10 transactions
    yr_counts = df.groupby("annee").size()
    yr_ref    = int(yr_counts[yr_counts >= 10].index.max())
    idx_current = idx_used.get(yr_ref, idx_used.get(2024, 1.0))
    print(f"  Annee reference : {yr_ref}  idx={idx_current:.3f}")

    # Sauvegarder
    artifacts = {
        "section_te_map":  {k: float(v) for k,v in ste_map.items()},
        "market_idx":      {str(int(k)): round(float(v),4) for k,v in mkt_idx.items()},
        "market_idx_current": float(idx_current),
        "feature_cols":    list(X_all.columns),
        "n_train":         int(len(df)),
        "mape_approx":     15.0,  # % MAPE typique de ce modele
    }
    joblib.dump(model, MODEL_PKL)
    ARTIFACTS.write_text(json.dumps(artifacts, ensure_ascii=False, indent=2))
    print(f"Modele sauve: {MODEL_PKL}  ({len(df)} transactions)")
    return model, artifacts

def load_model():
    import joblib
    if not MODEL_PKL.exists() or not ARTIFACTS.exists():
        return train_and_save()
    model = joblib.load(MODEL_PKL)
    arts  = json.loads(ARTIFACTS.read_text())
    return model, arts

def load_qualitative_coeff():
    """Charge dvf/qualitative_coeff.json (calibré LOO MAPE ~20%)."""
    p = DVF_DIR / "qualitative_coeff.json"
    if p.exists():
        return json.loads(p.read_text())
    # Fallback si fichier absent
    return {
        "etat": {"cata":0.45,"renov":0.65,"moyen_r":0.80,"moyen":0.90,
                 "bon":1.00,"tres_bon":1.13,"luxe":1.33},
        "vue":  {"default":1.00,"vue_massif":1.12,"vue_mont_blanc":1.23,
                 "vue_MB_section_D":0.96},
        "type_bien": {"maison":1.00,"chalet":1.00},
        "loi_fourchette": {"low_pct":-0.18,"high_pct":0.18},
    }

# ── Prediction ────────────────────────────────────────────────────────────
def predict(section, surface, surf_terrain, plu_zone,
            pieces=None, altitude=None, dist_centre=None, dist_ski=None):
    """
    Retourne dict:
        valeur        : estimation centrale (euros courants)
        val_low       : borne basse -15%
        val_high      : borne haute +15%
        prix_m2       : valeur / surface
        val_bati      : part batie seule
        val_terrain   : part terrain seule
        idx_current   : index marche utilise
    """
    model, arts = load_model()
    tr  = _load_terrain_ref()
    ste = arts["section_te_map"]

    sec  = section.upper()
    defs = SECTION_DEFAULTS.get(sec, SECTION_DEFAULTS["G"])
    if altitude   is None: altitude   = defs["altitude"]
    if dist_centre is None: dist_centre = defs["dist_centre"]
    if dist_ski    is None: dist_ski    = defs["dist_ski"]
    if pieces      is None: pieces      = max(1., surface / 20.)

    X = build_features(
        section=sec, surface=surface, surf_terrain=surf_terrain,
        plu_zone=plu_zone, pieces=pieces, annee=2025,
        altitude=altitude, dist_centre=dist_centre, dist_ski=dist_ski,
        section_te_map=ste, tr=tr,
    )

    # Aligner les colonnes sur celles du modele
    feat_cols = arts.get("feature_cols", list(X.columns))
    for col in feat_cols:
        if col not in X.columns:
            X[col] = 0.
    X = X[feat_cols]

    idx = arts["market_idx_current"]
    log_val_norm = float(model.predict(X)[0])
    val_norm     = np.exp(log_val_norm)
    val          = val_norm * idx

    ci           = arts.get("mape_approx", 15.) / 100.
    val_bati_est = surface  * ste.get(sec, float(np.mean(list(ste.values()))))
    val_ter_est  = (surf_terrain * _load_terrain_ref().get(sec, {}).get("U", 623.)
                    if plu_zone.upper() == "U" else
                    surf_terrain * _load_terrain_ref().get(sec, {}).get("N", 52.))
    return {
        "valeur":      round(val),
        "val_low":     round(val * (1 - ci)),
        "val_high":    round(val * (1 + ci)),
        "prix_m2":     round(val / surface),
        "val_bati":    round(val_bati_est * idx),
        "val_terrain": round(val_ter_est),
        "idx_current": round(idx, 3),
        "section":     sec,
        "plu":         plu_zone.upper(),
    }

# ── Estimation avec corrections qualitatives ─────────────────────────────
def predict_with_qualitative(section, surface, surf_terrain, plu_zone,
                              etat="bon", vue="default", type_bien="maison",
                              exposition="mixte", parking="aucun",
                              pieces=None, altitude=None,
                              dist_centre=None, dist_ski=None):
    """
    AVM + corrections qualitatives (état / vue / type / exposition / parking).
    Retourne dict étendu avec fourchette ±18% (LOO MAPE calibré).

    etat       : cata | renov | moyen_r | moyen | bon | tres_bon | luxe
    vue        : default | vue_massif | vue_mont_blanc
    type_bien  : maison | chalet
    exposition : nord | est | mixte | sud_est | sud
    parking    : aucun | place_ext | garage_simple | garage_double
    """
    base = predict(section, surface, surf_terrain, plu_zone,
                   pieces=pieces, altitude=altitude,
                   dist_centre=dist_centre, dist_ski=dist_ski)
    q = load_qualitative_coeff()

    # Coefficient état — appliqué seulement sur la part bâtie, pas terrain
    # (terrain ne se déprécie pas avec l'état du bâti)
    c_etat_raw = q["etat"].get(etat, 1.0)
    val_bati_est  = base.get("val_bati",  base["valeur"] * 0.5)
    val_terr_est  = base.get("val_terrain", base["valeur"] * 0.5)
    val_total_est = val_bati_est + val_terr_est
    if val_total_est > 0:
        ratio_terrain = val_terr_est / val_total_est
    else:
        ratio_terrain = 0.0
    # c_état effectif = mix terrain (stable) + bâti (dégradé)
    c_etat = ratio_terrain * 1.0 + (1.0 - ratio_terrain) * c_etat_raw

    # Coefficient vue — si section D + vue MB → utiliser override D
    sec = section.upper()
    if vue == "vue_mont_blanc" and sec == "D":
        c_vue = q["vue"].get("vue_MB_section_D", 0.96)
    else:
        c_vue = q["vue"].get(vue, 1.0)

    # Coefficient type
    c_type = q["type_bien"].get(type_bien, 1.0)

    # Coefficient exposition
    c_expo = q.get("exposition", {}).get(exposition, 1.0)

    # Coefficient parking
    c_park = q.get("parking", {}).get(parking, 1.0)

    val_corr = base["valeur"] * c_etat * c_vue * c_type * c_expo * c_park
    fq = q.get("loi_fourchette", {"low_pct": -0.18, "high_pct": 0.18})

    return {
        **base,
        "valeur_brut":  base["valeur"],
        "valeur":       round(val_corr),
        "val_low":      round(val_corr * (1 + fq["low_pct"])),
        "val_high":     round(val_corr * (1 + fq["high_pct"])),
        "prix_m2":      round(val_corr / surface),
        "c_etat":       c_etat,
        "c_etat_raw":   c_etat_raw,
        "ratio_terrain": round(ratio_terrain, 2),
        "c_vue":        c_vue,
        "c_type":       c_type,
        "c_expo":       c_expo,
        "c_park":       c_park,
        "etat":         etat,
        "vue":          vue,
        "type_bien":    type_bien,
        "exposition":   exposition,
        "parking":      parking,
        "qualitative":  True,
    }

# ── Affichage ─────────────────────────────────────────────────────────────
def print_result(res, surface, surf_terrain, prix_demande=None):
    v     = res["valeur"]
    lo    = res["val_low"]
    hi    = res["val_high"]
    pm2   = res["prix_m2"]
    vt    = res["val_terrain"]

    print()
    print("=" * 54)
    print(f"  ESTIMATION AVM  —  Section {res['section']}  |  PLU {res['plu']}")
    print(f"  {surface:.0f} m2 bati  +  {surf_terrain:.0f} m2 terrain")
    print("=" * 54)
    print(f"  Valeur estimee  :  {v/1e6:.3f} M€")
    print(f"  Fourchette      :  [{lo/1e6:.3f} - {hi/1e6:.3f} M€]  +/-15%")
    print(f"  Prix/m2 implicite: {pm2:,.0f} €/m2")
    # Decomposition terrain indicative (hors modele)
    if surf_terrain > 0 and vt > 0:
        vt_clamp = min(vt, v * 0.60)   # cap a 60% pour rester coherent
        vb_impl  = v - vt_clamp
        print(f"  ├─ part bati    :  ~{vb_impl/1e6:.3f} M€  (indicatif)")
        print(f"  └─ part terrain :  ~{vt_clamp/1e6:.3f} M€  ({res['plu']} @ ref cadastre)")
    print(f"  Index marche    :  {res['idx_current']:.3f}  (ref 2022=1.000)")

    if prix_demande:
        ratio = prix_demande / v
        if   ratio <= 0.75: score, label = 95, "EXCELLENTE AFFAIRE"
        elif ratio <= 0.85: score, label = 80, "BONNE AFFAIRE"
        elif ratio <= 0.95: score, label = 65, "SOUS-MARCHE"
        elif ratio <= 1.05: score, label = 50, "PRIX MARCHE"
        elif ratio <= 1.20: score, label = 30, "AU-DESSUS MARCHE"
        elif ratio <= 1.40: score, label = 15, "SURCOTE"
        else:               score, label = 5,  "TRES SURCOTE"
        print()
        print(f"  Prix demande    :  {prix_demande/1e6:.3f} M€")
        print(f"  Ratio prix/AVM  :  {ratio:.2f}  →  [{score}/100]  {label}")
        ecart = prix_demande - v
        print(f"  Ecart vs marche :  {ecart/1e3:+.0f} k€  ({(ratio-1)*100:+.1f}%)")

    print("=" * 54)
    print()

# ── CLI ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AVM Chamonix — estimation DVF XGBoost")
    parser.add_argument("section",      nargs="?", help="Section cadastrale (A/B/C/D/E/G)")
    parser.add_argument("surface",      nargs="?", type=float, help="Surface habitable (m2)")
    parser.add_argument("terrain",      nargs="?", type=float, help="Terrain (m2)")
    parser.add_argument("plu",          nargs="?", help="Zone PLU (U/N/A)")
    parser.add_argument("--prix",       type=float, help="Prix demande (euros) pour calculer le score")
    parser.add_argument("--altitude",   type=float, help="Altitude (m) — optionnel, defaut section")
    parser.add_argument("--dc",         type=float, help="Distance centre (km) — optionnel")
    parser.add_argument("--dsk",        type=float, help="Distance remontees (km) — optionnel")
    parser.add_argument("--pieces",     type=float, help="Nombre de pieces — optionnel")
    parser.add_argument("--retrain",    action="store_true", help="Forcer re-entrainement")
    args = parser.parse_args()

    if args.retrain and MODEL_PKL.exists():
        MODEL_PKL.unlink()
        ARTIFACTS.unlink(missing_ok=True)
        print("Modele supprime — re-entrainement force...")

    # Mode interactif si args manquants
    SECTIONS = ["A","B","C","D","E","G"]
    PLUZONES = ["U","N","A","AU"]

    section  = args.section
    surface  = args.surface
    terrain  = args.terrain
    plu      = args.plu
    prix_dem = args.prix

    # Mode interactif uniquement si AUCUN arg positionnel fourni
    interactive = (section is None)

    if interactive:
        print()
        print("=== AVM Chamonix  —  Entrez les caracteristiques du bien ===")
        print()
        print("Sections cadastrales disponibles:")
        for s, d in SECTION_DEFAULTS.items():
            print(f"  {s} : alt={d['altitude']:.0f}m  dist_centre={d['dist_centre']:.2f}km"
                  f"  dist_ski={d['dist_ski']:.2f}km")
        print()
        while True:
            section = input("Section cadastrale (A/B/C/D/E/G) : ").strip().upper()
            if section in SECTIONS: break
            print(f"  Section invalide. Valeurs valides: {', '.join(SECTIONS)}")

    if surface is None:
        surface = float(input("Surface habitable (m2) : ").strip()) if interactive else 0.

    if terrain is None:
        terrain = float(input("Terrain (m2, 0 si aucun) : ").strip()) if interactive else 0.

    if not plu:
        if interactive:
            while True:
                plu = input("Zone PLU (U=constructible / N=naturel / A=agricole) : ").strip().upper()
                if plu in PLUZONES: break
                print(f"  PLU invalide. Valeurs valides: {', '.join(PLUZONES)}")
        else:
            plu = "U"

    if prix_dem is None and interactive:
        p_str = input("Prix demande en euros (Entree = passer) : ").strip()
        if p_str:
            prix_dem = float(p_str.replace(" ","").replace(",","."))

    res = predict(
        section     = section,
        surface     = surface,
        surf_terrain= terrain,
        plu_zone    = plu,
        pieces      = args.pieces,
        altitude    = args.altitude,
        dist_centre = args.dc,
        dist_ski    = args.dsk,
    )
    print_result(res, surface, terrain, prix_dem)

if __name__ == "__main__":
    main()
