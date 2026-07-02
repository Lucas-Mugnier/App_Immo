"""
_update_avm_dashboard.py
========================
Script maitre : met a jour les predictions AVM dans dashboard.html
- Appartements Chamonix  → avm_appart_cham_model.pkl  → const rows (dashboard.html)
- Maisons Chamonix       → avm_maison_cham_model.pkl  → DB maisons + const MAISONS (dashboard.html)
"""
import re, json, pickle, sqlite3, numpy as np, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

BASE  = Path(__file__).parent
DVF   = BASE / "dvf"
DASH  = BASE / "dashboard.html"

ANNEE_PREDICT = 2026

# ─────────────────────────────────────────────────────────────────────────────
# 1. CHARGEMENT MODELES
# ─────────────────────────────────────────────────────────────────────────────
with open(DVF / "avm_appart_cham_model.pkl", "rb") as f:
    cham_apt = pickle.load(f)

with open(DVF / "avm_appart_model.pkl", "rb") as f:
    vallee_apt = pickle.load(f)

with open(DVF / "avm_maison_cham_model.pkl", "rb") as f:
    cham_mai = pickle.load(f)

print(f"Appart Chamonix : MAPE {cham_apt['mape_cv']:.1%}")
print(f"Appart Vallee   : MAPE {vallee_apt.get('mape_cv','?')}")
print(f"Maison Chamonix : MAPE {cham_mai['mape_cv']:.1%}  n={cham_mai.get('n_train','?')}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. PREDICT APPART
# ─────────────────────────────────────────────────────────────────────────────
def predict_appart(surface, rooms, section=None):
    le_sec   = cham_apt["le_sec"]
    features = cham_apt["features"]
    med      = cham_apt["med"]
    model    = cham_apt["model"]
    annee_ref= cham_apt["annee_ref"]

    # Section par defaut = G (Moussoux/Centre, la plus frequente)
    sec = section or "G"
    if sec not in list(le_sec.classes_):
        sec = "G"
    sec_enc = list(le_sec.classes_).index(sec)

    row = {
        "log_surf":  np.log(float(max(surface, 1))),
        "pieces_f":  float(max(1, min(10, rooms or 2))),
        "sec_enc":   float(sec_enc),
        "annee_f":   float(ANNEE_PREDICT - annee_ref),
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


# ─────────────────────────────────────────────────────────────────────────────
# 3. PREDICT MAISON
# ─────────────────────────────────────────────────────────────────────────────
def predict_maison(surface, rooms, terrain, section=None, lat=None, lon=None):
    le_sec   = cham_mai["le_sec"]
    features = cham_mai["features"]
    med      = cham_mai["med"]
    model    = cham_mai["model"]
    annee_ref= cham_mai["annee_ref"]

    sec = (section or "G").upper()
    if sec not in list(le_sec.classes_):
        sec = "G"
    sec_enc  = list(le_sec.classes_).index(sec)
    terrain  = float(terrain or surface * 2.5)

    row = {
        "log_surf": np.log(float(max(surface, 1))),
        "pieces_f": float(max(1, min(12, rooms or 4))),
        "sec_enc":  float(sec_enc),
        "annee_f":  float(ANNEE_PREDICT - annee_ref),
        "ndep_f":   0.0,
        "lots_f":   1.0,
        "has_ter":  1.0 if terrain > 0 else 0.0,
        "log_ter":  float(np.log1p(terrain)),
        "lat_f":    float(lat  if lat  is not None else med["lat"]),
        "lon_f":    float(lon  if lon  is not None else med["lon"]),
        "alt_f":    float(med["alt"]),
        "dist_f":   float(med["dist"]),
        "ski_f":    float(med["ski"]),
    }
    X = np.array([[row[f] for f in features]])
    return round(float(np.exp(model.predict(X)[0])))


# ─────────────────────────────────────────────────────────────────────────────
# 4. MISE A JOUR APPARTEMENTS (const rows dans dashboard.html)
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- APPARTEMENTS ---")
html = DASH.read_text(encoding="utf-8")
match = re.search(r'(const rows = )(\[.*?\]);', html, re.DOTALL)
if not match:
    raise ValueError("Bloc 'const rows' introuvable dans dashboard.html")

rows = json.loads(match.group(2))
CHAMONIX_LOCS = {"Chamonix", "Argentiere"}
LOC_TO_COMMUNE = {
    "Chamonix": "CHAMONIX MONT BLANC", "Argentiere": "CHAMONIX MONT BLANC",
    "Les Houches": "LES HOUCHES", "Saint-Gervais": "SAINT GERVAIS LES BAINS",
    "Sallanches": "SALLANCHES", "Passy": "PASSY", "Servoz": "SERVOZ", "Domancy": "DOMANCY",
}
DEFAULT_SEC_VALLEE = {
    "LES HOUCHES": "C", "SAINT GERVAIS LES BAINS": "A",
    "SALLANCHES": "A", "PASSY": "J", "SERVOZ": "A", "DOMANCY": "A",
}
GEO_MED = {
    "CHAMONIX MONT BLANC":     {"lat":45.923,"lon":6.869,"alt":1043.0,"dist":0.731,"ski":0.320},
    "LES HOUCHES":             {"lat":45.894,"lon":6.797,"alt":1015.0,"dist":1.452,"ski":0.376},
    "SAINT GERVAIS LES BAINS": {"lat":45.889,"lon":6.709,"alt":833.5, "dist":0.798,"ski":0.378},
    "SALLANCHES":              {"lat":45.937,"lon":6.634,"alt":550.0, "dist":0.540,"ski":3.610},
    "PASSY":                   {"lat":45.927,"lon":6.707,"alt":682.0, "dist":1.992,"ski":2.447},
    "SERVOZ":                  {"lat":45.931,"lon":6.763,"alt":814.0, "dist":1.297,"ski":2.482},
    "DOMANCY":                 {"lat":45.912,"lon":6.653,"alt":566.0, "dist":3.383,"ski":2.123},
}

def predict_vallee(surface, rooms, commune):
    le_com   = vallee_apt["le_commune"]
    le_sec   = vallee_apt["le_section"]
    features = vallee_apt["features"]
    med      = vallee_apt["med"]
    model    = vallee_apt["model"]
    annee_ref= vallee_apt.get("annee_ref", 2024)
    classes_com = list(le_com.classes_)
    com_enc  = classes_com.index(commune) if commune in classes_com else 0
    sec      = DEFAULT_SEC_VALLEE.get(commune, "A")
    classes_sec = list(le_sec.classes_)
    sec_enc  = classes_sec.index(sec) if sec in classes_sec else 0
    geo      = GEO_MED.get(commune, med)
    row = {
        "log_surface": np.log(float(max(surface, 1))),
        "pieces_f":    float(max(1, min(10, rooms or 2))),
        "commune_enc": float(com_enc),
        "section_enc": float(sec_enc),
        "annee_f":     float(ANNEE_PREDICT - annee_ref),
        "n_dep_f":     0.0,
        "alt_f":       float(geo.get("alt",  med["alt"])),
        "dist_f":      float(geo.get("dist", med["dist"])),
        "ski_f":       float(geo.get("ski",  med["ski"])),
        "lat_f":       float(geo.get("lat",  med["lat"])),
        "lon_f":       float(geo.get("lon",  med["lon"])),
    }
    X = np.array([[row[f] for f in features]])
    return round(float(np.exp(model.predict(X)[0])))

n_apt_cham = n_apt_vallee = n_apt_null = 0
for r in rows:
    surface  = r.get("surface")
    rooms    = r.get("rooms")
    location = r.get("location", "")
    price    = r.get("price")
    commune  = LOC_TO_COMMUNE.get(location)
    if not surface or surface < 10 or not commune:
        r["avm_pred"] = None; r["avm_ratio"] = None; r["avm_model"] = None
        n_apt_null += 1
        continue
    if location in CHAMONIX_LOCS:
        pred  = predict_appart(surface, rooms)
        model_name = "chamonix_apt"
    else:
        pred  = predict_vallee(surface, rooms, commune)
        model_name = "vallee_apt"
    if pred and price and price > 0:
        r["avm_pred"]  = pred
        r["avm_ratio"] = round(pred / price, 3)
        r["avm_model"] = model_name
        if location in CHAMONIX_LOCS: n_apt_cham += 1
        else: n_apt_vallee += 1
    else:
        r["avm_pred"] = None; r["avm_ratio"] = None; r["avm_model"] = None
        n_apt_null += 1

print(f"Apparts mis a jour : {n_apt_cham} Chamonix + {n_apt_vallee} vallee, {n_apt_null} sans pred")
for r in [x for x in rows if x.get("avm_model")][:4]:
    print(f"  {r['location']:12s} {r.get('surface',0):.0f}m2  "
          f"{r.get('price',0):>9,} -> {r['avm_pred']:>9,}  x{r['avm_ratio']:.2f}")

new_json = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
html = html[:match.start()] + match.group(1) + new_json + ";" + html[match.end():]


# ─────────────────────────────────────────────────────────────────────────────
# 5. MISE A JOUR MAISONS (DB + const MAISONS dans dashboard.html)
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- MAISONS ---")
con = sqlite3.connect(DVF / "listings_chamonix.db")
maisons_db = con.execute("""
    SELECT id, surface, surf_terrain, pieces, section, lat, lon, prix
    FROM maisons
    WHERE statut = 'actif' OR statut IS NULL
""").fetchall()

p80_mai = float(cham_mai.get("p80_err", 0.18))
n_mai_ok = n_mai_null = 0
updates = []
for row in maisons_db:
    rid, surface, terrain, pieces, section, lat, lon, prix = row
    if not surface or surface < 20:
        updates.append((None, None, None, rid))
        n_mai_null += 1
        continue
    pred = predict_maison(surface, pieces, terrain, section, lat, lon)
    ratio = round(pred / prix, 3) if pred and prix and prix > 0 else None
    # Score 0-100 : ratio > 1 = bonne affaire
    score = min(100, max(0, round(50 + (ratio - 1) * 100))) if ratio else None
    updates.append((pred, ratio, score, rid))
    n_mai_ok += 1

con.executemany("UPDATE maisons SET avm_pred=?, avm_ratio=?, avm_score=? WHERE id=?", updates)
con.commit()
print(f"Maisons mises a jour : {n_mai_ok} predictions, {n_mai_null} sans pred")

# Relire les maisons pour le JS
SEC_LABELS = {"A":"La Tour","B":"Argentière","C":"Les Praz/Tines","D":"Centre est","E":"Les Bossons","G":"Moussoux/Centre"}
cols = ["id","url","titre","adresse_raw","section","surface","surf_terrain","pieces",
        "prix","prix_initial","nb_baisses","historique_prix",
        "avm_pred","avm_ratio","avm_score","first_seen","notes","lat","lon"]
rows_db = con.execute(f"""
    SELECT {','.join(cols)} FROM maisons
    WHERE statut = 'actif' OR statut IS NULL
    ORDER BY avm_score DESC, prix ASC
""").fetchall()
con.close()

maisons_js = []
for row in rows_db:
    d = dict(zip(cols, row))
    try: d["historique_prix"] = json.loads(d["historique_prix"] or "[]")
    except: d["historique_prix"] = []
    if d["avm_pred"]:  d["avm_pred"]  = round(d["avm_pred"])
    if d["avm_ratio"]: d["avm_ratio"] = round(d["avm_ratio"], 3)
    maisons_js.append(d)

# Exemple
for m in [x for x in maisons_js if x.get("avm_pred")][:4]:
    print(f"  {m['adresse_raw'][:30]:30s} {m.get('surface',0):.0f}m2  "
          f"{m.get('prix',0):>10,} -> {m['avm_pred']:>10,}  x{m['avm_ratio']:.2f}")

# Remplace const MAISONS dans le dashboard
new_maisons_json = json.dumps(maisons_js, ensure_ascii=False, separators=(",", ":"), default=str)
m_match = re.search(r'const MAISONS = \[.*?\];', html, re.DOTALL)
if m_match:
    html = html[:m_match.start()] + f"const MAISONS = {new_maisons_json};" + html[m_match.end():]
    print(f"const MAISONS remplace ({len(maisons_js)} maisons)")
else:
    print("WARN: const MAISONS introuvable — maisons tab peut-etre pas encore injecte")

# Mise a jour fourchette P80 dans le JS
old_fourch = re.search(r'const FOURCHETTE_PCT = [\d.]+;', html)
if old_fourch:
    html = html[:old_fourch.start()] + f"const FOURCHETTE_PCT = {p80_mai:.3f};" + html[old_fourch.end():]

# Mise a jour MAPE dans stats bar
old_prec = re.search(r'Précision modèle <strong>~[\d.]+% LOO</strong>', html)
if old_prec:
    html = html[:old_prec.start()] + f"Précision modèle <strong>~{p80_mai*100:.0f}% P80</strong>" + html[old_prec.end():]


# ─────────────────────────────────────────────────────────────────────────────
# 6. SAUVEGARDE
# ─────────────────────────────────────────────────────────────────────────────
DASH.write_text(html, encoding="utf-8")
size_kb = len(html) // 1024
print(f"\ndashboard.html mis a jour ({size_kb} KB)")
print(f"  Apparts : {n_apt_cham} Chamonix + {n_apt_vallee} vallee")
print(f"  Maisons : {n_mai_ok} predictions (P80=±{p80_mai*100:.0f}%)")
print(f"  Appart MAPE CV : {cham_apt['mape_cv']:.1%}")
print(f"  Maison MAPE CV : {cham_mai['mape_cv']:.1%}")
