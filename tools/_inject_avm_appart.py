"""
_inject_avm_appart.py
======================
Calcule avm_pred + avm_ratio pour chaque annonce appartement dans dashboard.html.

Routing modeles :
  Chamonix + Argentiere  → avm_appart_cham_model.pkl  (MAPE 19.1% CV, 1437 tx Chamonix)
  Autres communes        → avm_appart_model.pkl        (MAPE 15.6% CV, all-communes)
"""

import re, json, pickle, numpy as np
from pathlib import Path

BASE = Path(__file__).parent

# ── Chargement modeles ────────────────────────────────────────────────────────
with open(BASE / "dvf" / "avm_appart_cham_model.pkl", "rb") as f:
    cham = pickle.load(f)

with open(BASE / "dvf" / "avm_appart_model.pkl", "rb") as f:
    vallée = pickle.load(f)

ANNEE_PREDICT = 2026
ANNEE_REF     = 2024

# Locations Chamonix commune (Argentiere = hameau de Chamonix)
CHAMONIX_LOCS = {"Chamonix", "Argentiere"}

# ── Medians geo par commune ───────────────────────────────────────────────────
GEO_MED = {
    "CHAMONIX MONT BLANC":    {"lat":45.923,"lon":6.869,"alt":1043.0,"dist":0.731,"ski":0.320},
    "LES HOUCHES":            {"lat":45.894,"lon":6.797,"alt":1015.0,"dist":1.452,"ski":0.376},
    "SAINT GERVAIS LES BAINS":{"lat":45.889,"lon":6.709,"alt":833.5, "dist":0.798,"ski":0.378},
    "SALLANCHES":             {"lat":45.937,"lon":6.634,"alt":550.0, "dist":0.540,"ski":3.610},
    "PASSY":                  {"lat":45.927,"lon":6.707,"alt":682.0, "dist":1.992,"ski":2.447},
    "SERVOZ":                 {"lat":45.931,"lon":6.763,"alt":814.0, "dist":1.297,"ski":2.482},
    "DOMANCY":                {"lat":45.912,"lon":6.653,"alt":566.0, "dist":3.383,"ski":2.123},
}

LOC_TO_COMMUNE = {
    "Chamonix":      "CHAMONIX MONT BLANC",
    "Argentiere":    "CHAMONIX MONT BLANC",
    "Les Houches":   "LES HOUCHES",
    "Saint-Gervais": "SAINT GERVAIS LES BAINS",
    "Sallanches":    "SALLANCHES",
    "Passy":         "PASSY",
    "Servoz":        "SERVOZ",
    "Domancy":       "DOMANCY",
}

# Section par defaut Chamonix (mode DVF = G)
DEFAULT_SEC_CHAM = "G"

# Section par defaut autres communes
DEFAULT_SEC_VALLÉE = {
    "LES HOUCHES":            "C",
    "SAINT GERVAIS LES BAINS":"A",
    "SALLANCHES":             "A",
    "PASSY":                  "J",
    "SERVOZ":                 "A",
    "DOMANCY":                "A",
}

# ── Prediction Chamonix ───────────────────────────────────────────────────────
def predict_cham(surface, rooms):
    """Modele Chamonix-only (section G par defaut)."""
    le_sec   = cham["le_sec"]
    features = cham["features"]
    med      = cham["med"]
    model    = cham["model"]

    sec_classes = list(le_sec.classes_)
    sec_enc = sec_classes.index(DEFAULT_SEC_CHAM) if DEFAULT_SEC_CHAM in sec_classes else 0

    row = {
        "log_surf":  np.log(float(surface)),
        "pieces_f":  float(max(1, min(10, rooms or 2))),
        "sec_enc":   float(sec_enc),
        "annee_f":   float(ANNEE_PREDICT - ANNEE_REF),
        "ndep_f":    0.0,
        "lots_f":    0.0,
        "alt_f":     float(med["alt"]),
        "dist_f":    float(med["dist"]),
        "ski_f":     float(med["ski"]),
        "lat_f":     float(med["lat"]),
        "lon_f":     float(med["lon"]),
    }
    X = np.array([[row[f] for f in features]])
    return round(float(np.exp(model.predict(X)[0])))


# ── Prediction all-communes ───────────────────────────────────────────────────
def predict_vallee(surface, rooms, commune):
    """Modele all-communes."""
    le_com   = vallée["le_commune"]
    le_sec   = vallée["le_section"]
    features = vallée["features"]
    med      = vallée["med"]
    model    = vallée["model"]

    classes_com = list(le_com.classes_)
    com_enc = classes_com.index(commune) if commune in classes_com else classes_com.index("CHAMONIX MONT BLANC")

    sec = DEFAULT_SEC_VALLÉE.get(commune, "A")
    classes_sec = list(le_sec.classes_)
    sec_enc = classes_sec.index(sec) if sec in classes_sec else 0

    geo = GEO_MED.get(commune, med)

    row = {
        "log_surface": np.log(float(surface)),
        "pieces_f":    float(max(1, min(10, rooms or 2))),
        "commune_enc": float(com_enc),
        "section_enc": float(sec_enc),
        "annee_f":     float(ANNEE_PREDICT - ANNEE_REF),
        "n_dep_f":     0.0,
        "alt_f":       float(geo.get("alt",  med["alt"])),
        "dist_f":      float(geo.get("dist", med["dist"])),
        "ski_f":       float(geo.get("ski",  med["ski"])),
        "lat_f":       float(geo.get("lat",  med["lat"])),
        "lon_f":       float(geo.get("lon",  med["lon"])),
    }
    X = np.array([[row[f] for f in features]])
    return round(float(np.exp(model.predict(X)[0])))


# ── Routing ───────────────────────────────────────────────────────────────────
def predict(surface, rooms, location):
    if not surface or surface < 10:
        return None
    commune = LOC_TO_COMMUNE.get(location)
    if commune is None:
        return None
    if location in CHAMONIX_LOCS:
        return predict_cham(surface, rooms)
    else:
        return predict_vallee(surface, rooms, commune)


# ── Lecture dashboard.html ────────────────────────────────────────────────────
print("Lecture dashboard.html ...")
dash_path = BASE / "dashboard.html"
content = dash_path.read_text(encoding="utf-8")

match = re.search(r'(const rows = )(\[.*?\]);', content, re.DOTALL)
if not match:
    raise ValueError("Bloc 'const rows' introuvable")

rows = json.loads(match.group(2))
print(f"{len(rows)} annonces trouvees")

# ── Calcul AVM ────────────────────────────────────────────────────────────────
n_cham = n_vallee = n_null = 0
for r in rows:
    surface  = r.get("surface")
    rooms    = r.get("rooms")
    location = r.get("location", "")
    price    = r.get("price")

    pred = predict(surface, rooms, location)
    if pred and price and price > 0:
        r["avm_pred"]  = pred
        r["avm_ratio"] = round(pred / price, 3)
        r["avm_model"] = "chamonix" if location in CHAMONIX_LOCS else "vallee"
        if location in CHAMONIX_LOCS:
            n_cham += 1
        else:
            n_vallee += 1
    else:
        r["avm_pred"]  = None
        r["avm_ratio"] = None
        r["avm_model"] = None
        n_null += 1

print(f"Chamonix model : {n_cham}  |  Vallee model : {n_vallee}  |  Sans pred : {n_null}")

# Exemples par modele
print("\n--- Chamonix (modele cham) ---")
for r in [x for x in rows if x.get("avm_model")=="chamonix"][:5]:
    print(f"  {r['location']:14s} {r['surface']:5.0f}m2 {r['rooms']}p  "
          f"{r['price']:>9,} -> {r['avm_pred']:>9,}  x{r['avm_ratio']:.2f}")

print("\n--- Vallee (modele all-communes) ---")
for r in [x for x in rows if x.get("avm_model")=="vallee"][:5]:
    print(f"  {r['location']:14s} {r['surface']:5.0f}m2 {r['rooms']}p  "
          f"{r['price']:>9,} -> {r['avm_pred']:>9,}  x{r['avm_ratio']:.2f}")

# ── Injection HTML ────────────────────────────────────────────────────────────
new_json  = json.dumps(rows, ensure_ascii=False, separators=(',', ':'))
new_block = match.group(1) + new_json + ";"
content_new = content[:match.start()] + new_block + content[match.end():]
dash_path.write_text(content_new, encoding="utf-8")
print(f"\ndashboard.html mis a jour ({len(rows)} annonces)")
