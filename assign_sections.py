# -*- coding: utf-8 -*-
"""
Attribue une section cadastrale à chaque listing SeLoger.
- Fixe si le quartier est non-ambigu (La Tour/Argentière → B)
- AVM-fit pour les autres : on essaie chaque section, on garde
  celle dont la prédiction est la plus proche du prix réel
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import sqlite3, json, math, pickle
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
DB   = BASE / "dvf" / "listings_chamonix.db"

# ── Chargement modèle + artefacts ─────────────────────────────────────────────
with open(BASE / "dvf" / "avm_model.pkl",      "rb") as f: model = pickle.load(f)
with open(BASE / "dvf" / "avm_artifacts.json", "r",  encoding="utf-8") as f:
    art = json.load(f)

SECTION_TE  = art["section_te_map"]   # {section: median_pm2}
EMP_IDX_CUR = art.get("market_idx_current", 1.185)

# Index empirique prioritaire
try:
    emp_art = json.load(open(BASE / "dvf" / "empirical_market_index.json"))
    EMP_IDX_CUR = emp_art.get("2025", emp_art.get("2024", EMP_IDX_CUR))
except FileNotFoundError:
    pass

# Terrain reference prices (section x PLU) — same as chamonix_avm.py / predict_avm.py
_TR = json.load(open(BASE / "dvf" / "terrain_ref_prix.json"))
def _ter_U(sec):
    r = _TR.get(sec.upper(), _TR.get("_GLOBAL", {}))
    v = r.get("U"); return float(v) if v else float(_TR["_GLOBAL"]["U"])
def _ter_N(sec):
    r = _TR.get(sec.upper(), _TR.get("_GLOBAL", {}))
    v = r.get("N", 52.); return float(v) if v else 52.

SECTIONS = sorted(SECTION_TE.keys())   # A B C D E G
FEATURE_COLS = art["feature_cols"]

# ── Paramètres géo fixes pour Chamonix ────────────────────────────────────────
# alt / dist_ski / dist_centre par quartier (approximations)
GEO = {
    # La Tour(1100m) / Argentière(1250m) / Les Praz(1060m) — moyenne ~1150m, 3-5km du centre
    "La Tour - Argentière - Les Praz":  dict(altitude=1150, dist_ski=0.4, dist_centre=3.5),
    # Les Tines = hameau entre Les Praz et Argentière
    "Les Tines":                        dict(altitude=1080, dist_ski=0.5, dist_centre=4.5),
    # Les Pélerins = quartier Chamonix, proche téléphérique
    "Les Pélerins - Le Betty":          dict(altitude=1060, dist_ski=0.5, dist_centre=1.0),
    # Bois du Bouchet = centre Chamonix sud
    "Chamonix Sud - Bois du Bouchet":   dict(altitude=1050, dist_ski=0.8, dist_centre=0.5),
    # Les Bossons (glacier, ~1000m) / Les Moussoux (flanc mont, ~1100m)
    "Les Bossons - Les Moussoux":       dict(altitude=1060, dist_ski=0.8, dist_centre=2.0),
    "Les Houches":                      dict(altitude=1010, dist_ski=0.4, dist_centre=7.0),
    "default":                          dict(altitude=1050, dist_ski=1.0, dist_centre=1.5),
}

# Sections candidates par quartier — mapping confirmé par l'utilisateur
# A=La Tour  B=Argentière  C=Les Tines/Les Praz  D=Centre est/Pélerins  E=Les Bossons  G=Centre ouest/Moussoux
CANDIDATES = {
    "La Tour - Argentière - Les Praz":  ["B", "C"],         # Argentière(B) + Les Praz(C) — La Tour(A) trop petit, à mettre à la main
    "Les Tines":                        ["C"],              # fixe
    "Les Pélerins - Le Betty":          ["D"],              # fixe
    "Chamonix Sud - Bois du Bouchet":   ["D", "G"],         # centre est=D, centre ouest/moussoux=G
    "Les Bossons - Les Moussoux":       ["E", "G"],         # Bossons=E, Moussoux=G
    "Les Houches":                      ["A", "B", "C", "D", "E", "G"],  # autre commune, pas dans modèle
    "default":                          SECTIONS,
}

PLU = "U"   # Chamonix = zone U par défaut (pas de données PLU dans scraps SeLoger)

# ── Build features — identique à predict_avm.py / chamonix_avm.py ─────────────
def build_features(section, surface, surf_terrain, pieces, annee=2022,
                   altitude=1050, dist_ski=1.0, dist_centre=1.5, plu=PLU):
    if surf_terrain is None or surf_terrain < 1:
        surf_terrain = surface * 2.5   # estimation si terrain manquant

    sec = section.upper()
    te  = SECTION_TE[sec]
    tu  = _ter_U(sec)
    tn  = _ter_N(sec)

    st = max(surf_terrain, 1.)
    ss = max(surface, 1.)

    # PLU flags
    is_U   = 1. if plu in ("U",)             else 0.
    is_N   = 1. if plu in ("N",)             else 0.
    is_A   = 1. if plu in ("A","HORS","AH")  else 0.
    is_AU  = 1. if plu in ("AU","AUC")       else 0.
    is_ERR = 1. if plu in ("ERR","?","")     else 0.

    # Surfaces terrain par zone PLU
    surf_U   = surf_terrain if is_U  else 0.
    surf_N   = surf_terrain if is_N  else 0.
    surf_ERR = surf_terrain if is_ERR else 0.

    # Valeurs monétaires (formule identique à l'entraînement)
    val_bati    = surface * te
    val_ter_U   = surf_U   * tu
    val_ter_N   = surf_N   * tn
    val_ter_ERR = surf_ERR * tu * 0.5
    val_terrain = val_ter_U + val_ter_N + val_ter_ERR
    val_total   = val_bati  + val_terrain

    surf_composite = surface + surf_U   # identique chamonix_avm.py build_X

    row = {
        "section_te":       te,
        "log_section_te":   math.log1p(te),
        "surface":          surface,
        "surf_terrain":     surf_terrain,
        "pieces":           float(pieces or 4),
        "annee":            float(annee),
        "annee_m2022":      float(annee) - 2022.,
        "log_surface":      math.log1p(surface),
        "log_terrain":      math.log1p(st),
        "sqrt_terrain":     math.sqrt(st),
        "ratio_ter":        st / ss,
        "plu_is_U":   is_U,  "plu_is_N":   is_N,  "plu_is_A":   is_A,
        "plu_is_AU":  is_AU, "plu_is_ERR": is_ERR,
        "val_bati":         val_bati,
        "val_ter_U":        val_ter_U,
        "val_ter_N":        val_ter_N,
        "val_ter_ERR":      val_ter_ERR,
        "val_terrain":      val_terrain,
        "val_total_est":    val_total,
        "val_ter_per_bati": val_terrain / (surface + 1.),
        "log_val_bati":     math.log1p(val_bati),
        "log_val_terrain":  math.log1p(val_terrain),
        "log_val_ter_U":    math.log1p(val_ter_U),
        "log_val_total":    math.log1p(val_total),
        "surf_composite":   surf_composite,
        "log_composite":    math.log1p(surf_composite),
        "altitude":         altitude,
        "dist_ski_lift":    dist_ski,
        "dist_centre":      dist_centre,
        "log_alt":          math.log1p(altitude),
        "alt_rel":          altitude - 950.,        # identique chamonix_avm.py
        "_tu":              tu,                     # terrain price rate €/m² zone U
        "_tn":              tn,                     # terrain price rate €/m² zone N
        "surf_U":           surf_U,
        "surf_N":           surf_N,
        "surf_ERR":         surf_ERR,
    }
    return [row[c] for c in FEATURE_COLS]

def predict_price(section, surface, surf_terrain, pieces, geo, plu=PLU):
    feat = build_features(section, surface, surf_terrain, pieces,
                          altitude=geo["altitude"],
                          dist_ski=geo["dist_ski"],
                          dist_centre=geo["dist_centre"],
                          plu=plu)
    raw = float(model.predict([feat])[0])
    return math.exp(raw) * EMP_IDX_CUR   # modele en log → exp, puis ajuste à 2025

# ── Assignation ───────────────────────────────────────────────────────────────
con = sqlite3.connect(DB)
rows = con.execute("""
    SELECT id, commune, adresse_raw, surface, surf_terrain, pieces, prix
    FROM maisons
    WHERE section IS NULL OR section = ''
    ORDER BY id
""").fetchall()

print(f"Listings sans section : {len(rows)}")
print(f"Sections disponibles  : {SECTIONS}")
print()

results = []
for (lid, commune, quartier, surface, surf_terrain, pieces, prix) in rows:
    if not surface or surface < 10 or surface > 400:
        continue   # < 10 = erreur parsing, > 400 = mega-chalet hors distribution AVM

    # SeLoger quartier labels unreliable → always use neutral geo for scrapped listings
    # DVF data uses real cadastral sections, but scraped ads can mislabel location by several km
    geo        = GEO["default"]
    candidates = CANDIDATES.get(quartier, CANDIDATES["default"])

    # Si 1 seul candidat → fixe, pas de calcul AVM
    if len(candidates) == 1:
        best_section = candidates[0]
        best_pred    = predict_price(best_section, surface, surf_terrain, pieces, geo)
        method       = "geo-fixe"
    else:
        # Essai de tous les candidats, on garde le plus proche du prix réel
        best_section, best_pred, best_err = None, None, float("inf")
        for sec in candidates:
            pred = predict_price(sec, surface, surf_terrain, pieces, geo)
            err  = abs(pred - prix) / prix
            if err < best_err:
                best_section, best_pred, best_err = sec, pred, err
        method = f"AVM-fit ({best_err:.1%} err)"

    avm_ratio = round(best_pred / prix, 3) if prix else None
    avm_score = None
    if avm_ratio:
        # 100 = parfait, -10 pts par 10% d'écart
        avm_score = max(0, min(100, round(100 - abs(1 - avm_ratio) * 100)))

    con.execute("""
        UPDATE maisons
        SET section=?, avm_pred=?, avm_ratio=?, avm_score=?
        WHERE id=?
    """, (best_section, round(best_pred), avm_ratio, avm_score, lid))

    results.append((lid, quartier, surface, surf_terrain or 0, prix, best_section, best_pred, avm_ratio, method))

con.commit()

# ── Rapport ───────────────────────────────────────────────────────────────────
print(f"{'ID':>3} {'Quartier':<35} {'Surf':>5} {'Terr':>5} {'Prix':>10}  {'Sec'} {'AVM Pred':>10}  {'Ratio':>6}  {'Methode'}")
print("─" * 105)
for r in results:
    lid, q, surf, terr, prix, sec, pred, ratio, meth = r
    print(f"{lid:>3} {q:<35} {surf:>5.0f} {terr:>5.0f} {prix/1e6:>9.2f}M  "
          f" {sec}  {pred/1e6:>9.2f}M  {ratio:>6.3f}  {meth}")

print()

# Stats par section assignée
from collections import Counter
sec_counts = Counter(r[5] for r in results)
print("Distribution sections assignées :")
for sec in sorted(sec_counts):
    n = sec_counts[sec]
    te = SECTION_TE[sec]
    subset = [r for r in results if r[5] == sec]
    avg_ratio = sum(r[7] for r in subset) / len(subset)
    print(f"  Section {sec} ({te:.0f} €/m² DVF)  → {n} listings  ratio moy AVM/prix = {avg_ratio:.3f}")

con.close()
print(f"\nDB mise a jour : {DB}")
