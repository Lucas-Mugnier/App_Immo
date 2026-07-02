"""
_inject_estimateur_clean.py
============================
Version idempotente de l'injection estimateur :
  1. Supprime TOUS les blocs estimateur existants (CSS, HTML, JS)
  2. Réinjecte UNE seule fois proprement
"""
import re, json, pickle, numpy as np, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
DVF  = BASE / "dvf"
DASH = BASE / "dashboard.html"
ANNEE_PREDICT = 2026

# ── 1. Charger modèles ────────────────────────────────────────────────────────
with open(DVF / "avm_appart_cham_model.pkl", "rb") as f: cham_apt = pickle.load(f)
with open(DVF / "avm_appart_model.pkl",       "rb") as f: vallee_apt = pickle.load(f)

SECTIONS_CHAM = list(cham_apt["le_sec"].classes_)
GEO_MED = {
    "LES HOUCHES":             {"lat":45.894,"lon":6.797,"alt":1015.0,"dist":1.452,"ski":0.376},
    "SAINT GERVAIS LES BAINS": {"lat":45.889,"lon":6.709,"alt":833.5, "dist":0.798,"ski":0.378},
    "SALLANCHES":              {"lat":45.937,"lon":6.634,"alt":550.0, "dist":0.540,"ski":3.610},
    "PASSY":                   {"lat":45.927,"lon":6.707,"alt":682.0, "dist":1.992,"ski":2.447},
    "SERVOZ":                  {"lat":45.931,"lon":6.763,"alt":814.0, "dist":1.297,"ski":2.482},
}
DEFAULT_SEC_VALLEE = {
    "LES HOUCHES":"C","SAINT GERVAIS LES BAINS":"A","SALLANCHES":"A","PASSY":"J","SERVOZ":"A",
}
def predict_cham(surface, rooms, section="G"):
    le_sec=cham_apt["le_sec"]; features=cham_apt["features"]; med=cham_apt["med"]
    model=cham_apt["model"]; annee_ref=cham_apt["annee_ref"]
    classes=list(le_sec.classes_); sec=section if section in classes else "G"
    row={"log_surf":np.log(float(max(surface,1))),"pieces_f":float(max(1,min(10,rooms))),
         "sec_enc":float(classes.index(sec)),"annee_f":float(ANNEE_PREDICT-annee_ref),
         "ndep_f":0.,"lots_f":0.,"alt_f":float(med["alt"]),"dist_f":float(med["dist"]),
         "ski_f":float(med["ski"]),"lat_f":float(med["lat"]),"lon_f":float(med["lon"])}
    return round(float(np.exp(model.predict(np.array([[row[f] for f in features]]))[0])))

def predict_vallee(surface, rooms, commune_dvf):
    le_com=vallee_apt["le_commune"]; le_sec=vallee_apt["le_section"]
    features=vallee_apt["features"]; med=vallee_apt["med"]
    model=vallee_apt["model"]; annee_ref=vallee_apt.get("annee_ref",2024)
    classes_com=list(le_com.classes_)
    com_enc=classes_com.index(commune_dvf) if commune_dvf in classes_com else 0
    sec=DEFAULT_SEC_VALLEE.get(commune_dvf,"A")
    classes_sec=list(le_sec.classes_)
    sec_enc=classes_sec.index(sec) if sec in classes_sec else 0
    geo=GEO_MED.get(commune_dvf,med)
    row={"log_surface":np.log(float(max(surface,1))),"pieces_f":float(max(1,min(10,rooms))),
         "commune_enc":float(com_enc),"section_enc":float(sec_enc),
         "annee_f":float(ANNEE_PREDICT-annee_ref),"n_dep_f":0.,
         "alt_f":float(geo.get("alt",med["alt"])),"dist_f":float(geo.get("dist",med["dist"])),
         "ski_f":float(geo.get("ski",med["ski"])),"lat_f":float(geo.get("lat",med["lat"])),
         "lon_f":float(geo.get("lon",med["lon"]))}
    return round(float(np.exp(model.predict(np.array([[row[f] for f in features]]))[0])))

# ── 2. Générer lookup table ───────────────────────────────────────────────────
SURFACES=[20,25,30,35,40,45,50,55,60,70,80,90,100,120,140,160,180,200]
ROOMS_LIST=[1,2,3,4,5]
COMMUNES_CFG={
    "Chamonix":     {"model":"cham","dvf":None,"def_sec":"G","mape":cham_apt["mape_cv"],"p80":cham_apt.get("p80_err",0.142)},
    "Argentière":   {"model":"cham","dvf":None,"def_sec":"B","mape":cham_apt["mape_cv"],"p80":cham_apt.get("p80_err",0.142)},
    "Les Houches":  {"model":"vallee","dvf":"LES HOUCHES","def_sec":"C","mape":float(vallee_apt.get("mape_cv",0.15)),"p80":0.25},
    "Saint-Gervais":{"model":"vallee","dvf":"SAINT GERVAIS LES BAINS","def_sec":"A","mape":float(vallee_apt.get("mape_cv",0.15)),"p80":0.25},
    "Sallanches":   {"model":"vallee","dvf":"SALLANCHES","def_sec":"A","mape":float(vallee_apt.get("mape_cv",0.15)),"p80":0.25},
    "Passy":        {"model":"vallee","dvf":"PASSY","def_sec":"J","mape":float(vallee_apt.get("mape_cv",0.15)),"p80":0.25},
    "Servoz":       {"model":"vallee","dvf":"SERVOZ","def_sec":"A","mape":float(vallee_apt.get("mape_cv",0.15)),"p80":0.25},
}
avm_lookup={}
for com,cfg in COMMUNES_CFG.items():
    entry={"surf":SURFACES,"mape":round(cfg["mape"],4),"p80":round(cfg["p80"],3),
           "model":"Chamonix XGBoost" if cfg["model"]=="cham" else "Vallée multi-communes","data":{}}
    for r in ROOMS_LIST:
        preds=[predict_cham(s,r,cfg["def_sec"]) if cfg["model"]=="cham" else predict_vallee(s,r,cfg["dvf"]) for s in SURFACES]
        entry["data"][str(r)]=preds
    if cfg["model"]=="cham":
        entry["sections"]={sec:{str(r):[predict_cham(s,r,sec) for s in SURFACES] for r in ROOMS_LIST} for sec in SECTIONS_CHAM}
    avm_lookup[com]=entry
    print(f"  {com}: OK")

table_json = json.dumps(avm_lookup, ensure_ascii=False, separators=(",",":"))
sec_opts   = {s:f"{s} - "+{"A":"La Tour","B":"Argentière","C":"Les Praz/Tines","D":"Centre-est","E":"Les Bossons","G":"Moussoux/Centre"}.get(s,f"Section {s}") for s in SECTIONS_CHAM}
sec_opts_json = json.dumps(sec_opts, ensure_ascii=False)

# ── 3. Contenu à injecter ─────────────────────────────────────────────────────
sec_opts_html = "\n".join(f'<option value="{s}"{"" if s!="G" else " selected"}>{lbl}</option>' for s,lbl in sec_opts.items())
communes_html = "\n".join(f'<option value="{c}">{c}</option>' for c in COMMUNES_CFG)

CSS = """
/* ── ESTIMATEUR-FAB-CSS-START ── */
.est-fab{position:fixed;bottom:24px;right:24px;z-index:900;
  background:linear-gradient(135deg,var(--accent) 0%,#1a3f8f 100%);
  color:#fff;border:none;border-radius:50px;padding:13px 22px;
  font-size:.9rem;font-weight:700;cursor:pointer;
  box-shadow:0 4px 20px rgba(27,68,173,.45);
  display:flex;align-items:center;gap:8px;transition:transform .15s,box-shadow .15s;}
.est-fab:hover{transform:translateY(-2px);box-shadow:0 6px 28px rgba(27,68,173,.6);}
.est-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;
  display:flex;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(4px);}
.est-overlay.hidden{display:none;}
.est-modal{background:var(--card);border-radius:16px;width:100%;max-width:600px;
  max-height:90vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,.3);border:1px solid var(--border);}
.est-header{padding:20px 24px 0;display:flex;align-items:center;justify-content:space-between;}
.est-header h2{margin:0;font-size:1.1rem;font-weight:800;}
.est-close{background:none;border:none;cursor:pointer;font-size:1.4rem;color:var(--muted);padding:4px 8px;border-radius:6px;}
.est-close:hover{background:var(--bg);}
.est-body{padding:20px 24px;}
.est-form-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px;}
.est-field{display:flex;flex-direction:column;gap:5px;}
.est-field label{font-size:.75rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;}
.est-field select,.est-field input[type=number]{padding:9px 12px;border:1.5px solid var(--border);border-radius:8px;
  background:var(--bg);color:var(--text);font-size:.9rem;width:100%;transition:border-color .15s;}
.est-field select:focus,.est-field input[type=number]:focus{outline:none;border-color:var(--accent);}
.est-surface-wrap{display:flex;align-items:center;gap:8px;}
.est-surface-wrap input[type=range]{flex:1;accent-color:var(--accent);}
.est-surface-wrap input[type=number]{width:80px;flex-shrink:0;}
.est-result{background:linear-gradient(135deg,#f0f4ff 0%,#e8f0fe 100%);
  border:1.5px solid #c7d7fb;border-radius:12px;padding:18px 20px;margin-bottom:16px;text-align:center;}
.est-result-val{font-size:2rem;font-weight:900;color:var(--accent);line-height:1.1;}
.est-result-range{font-size:.82rem;color:#4a6898;margin-top:4px;}
.est-result-meta{display:flex;justify-content:center;gap:16px;margin-top:10px;flex-wrap:wrap;}
.est-result-badge{font-size:.73rem;padding:3px 10px;border-radius:12px;font-weight:600;}
.est-result-badge.mape{background:#dbeafe;color:#1d4ed8;}
.est-result-badge.pm2{background:#dcfce7;color:#166534;}
.est-result-badge.model{background:#fef3c7;color:#78350f;}
.est-result-empty{color:var(--muted);font-size:.9rem;padding:20px 0;}
.est-section-title{font-size:.75rem;font-weight:700;color:var(--muted);text-transform:uppercase;
  letter-spacing:.04em;margin:16px 0 10px;display:flex;align-items:center;gap:8px;}
.est-section-title::after{content:'';flex:1;height:1px;background:var(--border);}
.est-chips-row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;}
.est-chip-label{font-size:.72rem;color:var(--muted);width:90px;flex-shrink:0;display:flex;align-items:center;font-weight:600;}
.est-chip{padding:5px 11px;border:1.5px solid var(--border);border-radius:16px;background:var(--card);
  cursor:pointer;font-size:.75rem;font-weight:600;color:var(--muted);transition:all .12s;white-space:nowrap;}
.est-chip:hover{border-color:var(--accent);color:var(--accent);}
.est-chip.active{border-color:var(--accent);background:var(--accent);color:#fff;}
.est-chip.positive{border-color:#16a34a;}.est-chip.active.positive{background:#16a34a;border-color:#16a34a;}
.est-chip.negative{border-color:#dc2626;}.est-chip.active.negative{background:#dc2626;border-color:#dc2626;}
.est-refined{background:var(--bg);border:1.5px solid var(--border);border-radius:10px;padding:14px 18px;margin-top:14px;}
.est-refined-row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;}
.est-refined-val{font-size:1.4rem;font-weight:800;color:var(--text);}
.est-refined-delta{font-size:.85rem;font-weight:700;}
.est-refined-delta.up{color:#16a34a;}.est-refined-delta.down{color:#dc2626;}.est-refined-delta.flat{color:var(--muted);}
.est-coeff-list{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px;}
.est-coeff-pill{font-size:.7rem;padding:2px 8px;border-radius:10px;font-weight:600;}
.est-coeff-pill.pos{background:#dcfce7;color:#166534;}.est-coeff-pill.neg{background:#fee2e2;color:#991b1b;}
.est-coeff-pill.neu{background:var(--bg);color:var(--muted);border:1px solid var(--border);}
.btn-affiner{padding:3px 9px;font-size:.72rem;border-radius:5px;border:1px solid var(--border);
  background:var(--bg);cursor:pointer;color:var(--muted);white-space:nowrap;transition:all .12s;}
.btn-affiner:hover{border-color:var(--accent);color:var(--accent);background:#f0f4ff;}
/* ── ESTIMATEUR-FAB-CSS-END ── */
"""

HTML_FAB = f"""
<!-- ESTIMATEUR-FAB-HTML-START -->
<button class="est-fab" id="est-fab-btn" onclick="openEstimateur()">
  📐 <span>Estimer</span>
</button>
<div class="est-overlay hidden" id="est-overlay" onclick="estOverlayClick(event)">
  <div class="est-modal" id="est-modal">
    <div class="est-header">
      <h2>📐 Estimateur AVM — Appartements</h2>
      <button class="est-close" onclick="closeEstimateur()">✕</button>
    </div>
    <div class="est-body">
      <div class="est-form-row">
        <div class="est-field">
          <label>Commune</label>
          <select id="est-commune" onchange="estUpdate()">
            {communes_html}
          </select>
        </div>
        <div class="est-field">
          <label>Pièces</label>
          <select id="est-rooms" onchange="estUpdate()">
            <option value="1">T1 / Studio</option>
            <option value="2">T2</option>
            <option value="3" selected>T3</option>
            <option value="4">T4</option>
            <option value="5">T5+</option>
          </select>
        </div>
      </div>
      <div class="est-form-row" style="align-items:center">
        <div class="est-field">
          <label>Surface (m²)</label>
          <div class="est-surface-wrap">
            <input type="range" id="est-surf-slider" min="15" max="200" value="55" step="1"
              oninput="document.getElementById('est-surf-num').value=this.value;estUpdate()">
            <input type="number" id="est-surf-num" value="55" min="15" max="300" step="1"
              oninput="document.getElementById('est-surf-slider').value=Math.min(200,this.value);estUpdate()">
          </div>
        </div>
        <div class="est-field" id="est-section-field">
          <label>Section cadastrale <span style="font-weight:400;color:var(--muted)">(opt.)</span></label>
          <select id="est-section" onchange="estUpdate()">
            {sec_opts_html}
          </select>
        </div>
      </div>
      <div class="est-result" id="est-result-box">
        <div class="est-result-empty">Renseignez les paramètres ci-dessus</div>
      </div>
      <div class="est-section-title">✨ Affineur — corrections qualitatives</div>
      <div style="font-size:.73rem;color:var(--muted);margin-bottom:10px">
        Corrections qualitatives basées sur la connaissance du marché Chamonix (non issues du modèle DVF).
      </div>
      <div class="est-chips-row">
        <span class="est-chip-label">État</span>
        <button class="est-chip negative" id="ec-etat-cata"     onclick="estChip('etat','cata')"     data-coeff="-0.45">💥 Catastrophique</button>
        <button class="est-chip negative" id="ec-etat-renov"    onclick="estChip('etat','renov')"    data-coeff="-0.28">🔧 À rénover</button>
        <button class="est-chip negative" id="ec-etat-moyen"    onclick="estChip('etat','moyen')"    data-coeff="-0.10">📦 Moyen</button>
        <button class="est-chip active"   id="ec-etat-bon"      onclick="estChip('etat','bon')"      data-coeff="0">🏠 Bon état</button>
        <button class="est-chip positive" id="ec-etat-tres_bon" onclick="estChip('etat','tres_bon')" data-coeff="+0.10">✨ Très bon</button>
        <button class="est-chip positive" id="ec-etat-neuf"     onclick="estChip('etat','neuf')"     data-coeff="+0.18">🆕 Neuf/VEFA</button>
      </div>
      <div class="est-chips-row">
        <span class="est-chip-label">Vue</span>
        <button class="est-chip active"   id="ec-vue-default"   onclick="estChip('vue','default')"   data-coeff="0">🪟 Standard</button>
        <button class="est-chip positive" id="ec-vue-vue_deg"   onclick="estChip('vue','vue_deg')"   data-coeff="+0.04">🌿 Dégagée</button>
        <button class="est-chip positive" id="ec-vue-vue_massif" onclick="estChip('vue','vue_massif')" data-coeff="+0.08">⛰ Massif</button>
        <button class="est-chip positive" id="ec-vue-vue_MB"    onclick="estChip('vue','vue_MB')"    data-coeff="+0.15">🏔 Mont-Blanc</button>
      </div>
      <div class="est-chips-row">
        <span class="est-chip-label">Étage</span>
        <button class="est-chip negative" id="ec-etg-rdc"      onclick="estChip('etage','rdc')"      data-coeff="-0.06">🚪 RDC</button>
        <button class="est-chip active"   id="ec-etg-inter"    onclick="estChip('etage','inter')"    data-coeff="0">🏢 Intermédiaire</button>
        <button class="est-chip positive" id="ec-etg-last"     onclick="estChip('etage','last')"     data-coeff="+0.04">🔝 Dernier</button>
        <button class="est-chip positive" id="ec-etg-last_asc" onclick="estChip('etage','last_asc')" data-coeff="+0.06">🔝🛗 Dernier+asc.</button>
      </div>
      <div class="est-chips-row">
        <span class="est-chip-label">Parking</span>
        <button class="est-chip active"   id="ec-park-aucun" onclick="estChip('parking','aucun')" data-coeff="0">❌ Aucun</button>
        <button class="est-chip positive" id="ec-park-ext"   onclick="estChip('parking','ext')"   data-coeff="+0.015">🅿 Place ext.</button>
        <button class="est-chip positive" id="ec-park-box"   onclick="estChip('parking','box')"   data-coeff="+0.04">🏠🅿 Box fermé</button>
        <button class="est-chip positive" id="ec-park-dbox"  onclick="estChip('parking','dbox')"  data-coeff="+0.06">🏠🏠 Double box</button>
      </div>
      <div class="est-chips-row">
        <span class="est-chip-label">Extérieur</span>
        <button class="est-chip active"   id="ec-ext-aucun"    onclick="estChip('ext','aucun')"    data-coeff="0">— Aucun</button>
        <button class="est-chip positive" id="ec-ext-balcon"   onclick="estChip('ext','balcon')"   data-coeff="+0.02">🌿 Balcon</button>
        <button class="est-chip positive" id="ec-ext-loggia"   onclick="estChip('ext','loggia')"   data-coeff="+0.02">🪟 Loggia</button>
        <button class="est-chip positive" id="ec-ext-terrasse" onclick="estChip('ext','terrasse')" data-coeff="+0.04">☀ Terrasse</button>
        <button class="est-chip positive" id="ec-ext-gde_terr" onclick="estChip('ext','gde_terr')" data-coeff="+0.07">🌞 Grande terrasse</button>
      </div>
      <div class="est-refined" id="est-refined-box" style="display:none">
        <div class="est-refined-row">
          <div>
            <div style="font-size:.75rem;color:var(--muted);font-weight:700;margin-bottom:2px">ESTIMATION AFFINÉE</div>
            <div class="est-refined-val" id="est-ref-val">—</div>
          </div>
          <div id="est-ref-delta" class="est-refined-delta flat">—</div>
        </div>
        <div class="est-coeff-list" id="est-ref-coeffs"></div>
      </div>
    </div>
  </div>
</div>
<!-- ESTIMATEUR-FAB-HTML-END -->
"""

JS = f"""
// ESTIMATEUR-JS-START
const AVM_LOOKUP = {table_json};
const AVM_SEC_OPTS = {sec_opts_json};
const EST_STATE = {{ etat:'bon', vue:'default', etage:'inter', parking:'aucun', ext:'aucun', baseAvm:null }};
const EST_COEFFS_A = {{
  etat:   {{ cata:-0.45, renov:-0.28, moyen:-0.10, bon:0, tres_bon:0.10, neuf:0.18 }},
  vue:    {{ default:0, vue_deg:0.04, vue_massif:0.08, vue_MB:0.15 }},
  etage:  {{ rdc:-0.06, inter:0, last:0.04, last_asc:0.06 }},
  parking:{{ aucun:0, ext:0.015, box:0.04, dbox:0.06 }},
  ext:    {{ aucun:0, balcon:0.02, loggia:0.02, terrasse:0.04, gde_terr:0.07 }},
}};
const EST_LABELS = {{
  etat:   {{ cata:'Catastrophique', renov:'À rénover', moyen:'Moyen', bon:'Bon état', tres_bon:'Très bon', neuf:'Neuf/VEFA' }},
  vue:    {{ default:'Vue standard', vue_deg:'Vue dégagée', vue_massif:'Vue massif', vue_MB:'Vue Mont-Blanc' }},
  etage:  {{ rdc:'RDC', inter:'Intermédiaire', last:'Dernier étage', last_asc:'Dernier+ascenseur' }},
  parking:{{ aucun:'Sans parking', ext:'Place ext.', box:'Box fermé', dbox:'Double box' }},
  ext:    {{ aucun:'Sans extérieur', balcon:'Balcon', loggia:'Loggia', terrasse:'Terrasse', gde_terr:'Grande terrasse' }},
}};

function avmInterp(commune, rooms, surface) {{
  const entry = AVM_LOOKUP[commune];
  if (!entry) return null;
  const r = String(Math.min(5, Math.max(1, Math.round(rooms))));
  const comm = document.getElementById('est-commune')?.value;
  const sec  = document.getElementById('est-section')?.value;
  let preds;
  if ((comm==='Chamonix'||comm==='Argentière') && sec && entry.sections?.[sec]) {{
    preds = entry.sections[sec][r];
  }} else {{
    preds = entry.data[r];
  }}
  if (!preds) return null;
  const surfs = entry.surf;
  if (surface <= surfs[0]) return preds[0];
  if (surface >= surfs[surfs.length-1]) return preds[preds.length-1];
  for (let i=0;i<surfs.length-1;i++) {{
    if (surface>=surfs[i]&&surface<=surfs[i+1]) {{
      const t=(surface-surfs[i])/(surfs[i+1]-surfs[i]);
      return Math.round(preds[i]+t*(preds[i+1]-preds[i]));
    }}
  }}
  return null;
}}

function estUpdate() {{
  const commune = document.getElementById('est-commune')?.value;
  const rooms   = parseFloat(document.getElementById('est-rooms')?.value)||2;
  const surface = parseFloat(document.getElementById('est-surf-num')?.value)||55;
  const isCham  = commune==='Chamonix'||commune==='Argentière';
  const secField= document.getElementById('est-section-field');
  if (secField) secField.style.display = isCham ? '' : 'none';
  const avm   = avmInterp(commune, rooms, surface);
  const entry = AVM_LOOKUP[commune];
  EST_STATE.baseAvm = avm;
  const box = document.getElementById('est-result-box');
  if (!avm||!entry) {{
    box.innerHTML='<div class="est-result-empty">Impossible de calculer — vérifiez les paramètres</div>';
    document.getElementById('est-refined-box').style.display='none'; return;
  }}
  const p80=entry.p80, lo=avm*(1-p80), hi=avm*(1+p80), pm2=Math.round(avm/surface);
  const fmtM=v=>(v/1e6).toFixed(3)+' M€', fmtK=v=>Math.round(v/1000)+'k€';
  box.innerHTML=`<div class="est-result-val">${{fmtM(avm)}}</div>
    <div class="est-result-range">${{fmtK(lo)}} – ${{fmtK(hi)}} (±${{Math.round(p80*100)}}% P80)</div>
    <div class="est-result-meta">
      <span class="est-result-badge mape">MAPE ~${{Math.round(entry.mape*100)}}%</span>
      <span class="est-result-badge pm2">${{pm2.toLocaleString('fr-FR')}} €/m²</span>
      <span class="est-result-badge model">${{entry.model}}</span>
    </div>`;
  estUpdateRefined();
}}

function estChip(group, val) {{
  EST_STATE[group]=val;
  document.querySelectorAll(`[id^="ec-${{group}}-"]`).forEach(el=>el.classList.remove('active'));
  document.getElementById(`ec-${{group}}-${{val}}`)?.classList.add('active');
  estUpdateRefined();
}}

function estUpdateRefined() {{
  const avm=EST_STATE.baseAvm;
  if (!avm) {{ document.getElementById('est-refined-box').style.display='none'; return; }}
  let total=1.0; const pills=[];
  for (const [group,val] of Object.entries(EST_STATE)) {{
    if (group==='baseAvm') continue;
    const c=EST_COEFFS_A[group]?.[val]??0;
    if (c===0) continue;
    total*=(1+c);
    const sign=c>0?'+':'';
    pills.push(`<span class="est-coeff-pill ${{c>0?'pos':'neg'}}">${{EST_LABELS[group]?.[val]||val}} ${{sign}}${{Math.round(c*100)}}%</span>`);
  }}
  if (Math.abs(total-1.0)<0.005) {{ document.getElementById('est-refined-box').style.display='none'; return; }}
  const refined=Math.round(avm*total), deltaP=Math.round((total-1)*100), sign=deltaP>0?'+':'';
  document.getElementById('est-refined-box').style.display='';
  document.getElementById('est-ref-val').textContent=(refined/1e6).toFixed(3)+' M€';
  document.getElementById('est-ref-delta').textContent=`${{sign}}${{deltaP}}% vs base`;
  document.getElementById('est-ref-delta').className=`est-refined-delta ${{deltaP>2?'up':deltaP<-2?'down':'flat'}}`;
  document.getElementById('est-ref-coeffs').innerHTML=pills.join('');
}}

function openEstimateur(surface, rooms, commune, price) {{
  if (commune) {{ const s=document.getElementById('est-commune'); if(s) s.value=commune; }}
  if (surface) {{ document.getElementById('est-surf-num').value=surface; document.getElementById('est-surf-slider').value=Math.min(200,surface); }}
  if (rooms)   {{ const s=document.getElementById('est-rooms'); if(s) s.value=String(Math.min(5,Math.max(1,Math.round(rooms)))); }}
  ['etat','vue','etage','parking','ext'].forEach(g=>estChip(g,g==='etat'?'bon':g==='vue'?'default':g==='etage'?'inter':'aucun'));
  document.getElementById('est-overlay').classList.remove('hidden');
  estUpdate();
}}
function closeEstimateur() {{ document.getElementById('est-overlay').classList.add('hidden'); }}
function estOverlayClick(e) {{ if(e.target===document.getElementById('est-overlay')) closeEstimateur(); }}
// ESTIMATEUR-JS-END
"""

# ── 4. Lire le dashboard et nettoyer ─────────────────────────────────────────
html = DASH.read_text(encoding="utf-8")
print(f"\nAvant nettoyage: {len(html)//1024} KB")

# Strip CSS entre markers
html = re.sub(r'/\* ── ESTIMATEUR-FAB-CSS-START ── \*/.*?/\* ── ESTIMATEUR-FAB-CSS-END ── \*/',
              '', html, flags=re.DOTALL)
# Strip anciens blocs CSS estimateur (sans markers)
html = re.sub(r'/\* ── Estimateur FAB \+ Modal ── \*/.*?(?=/\* ──|</style>)',
              '', html, flags=re.DOTALL)
# Strip HTML FAB entre markers
html = re.sub(r'<!-- ESTIMATEUR-FAB-HTML-START -->.*?<!-- ESTIMATEUR-FAB-HTML-END -->',
              '', html, flags=re.DOTALL)
# Strip anciens blocs HTML FAB (sans markers)
html = re.sub(r'\n<!-- ── Estimateur FAB ── -->.*?(?=\n</body>|\Z)',
              '', html, flags=re.DOTALL)
# Strip JS entre markers
html = re.sub(r'// ESTIMATEUR-JS-START.*?// ESTIMATEUR-JS-END\n?',
              '', html, flags=re.DOTALL)
# Strip anciens blocs JS (const AVM_LOOKUP + fonctions associées)
html = re.sub(r'const AVM_LOOKUP = \{.*?\};\s*\nconst AVM_SEC_OPTS',
              'const AVM_SEC_OPTS', html, flags=re.DOTALL)
# Strip le bout tronqué "// ESTIMATEUR AVM APPARTEMENTS" seul
html = re.sub(r'\n// ═{20,}\n// ESTIMATEUR AVM APPARTEMENTS\n',
              '\n', html)

print(f"Après nettoyage: {len(html)//1024} KB")
print(f"  AVM_LOOKUP restants: {html.count('AVM_LOOKUP')}")
print(f"  est-fab-btn: {html.count('est-fab-btn')}")
print(f"  function openEstimateur: {html.count('function openEstimateur(')}")

# ── 5. Injecter proprement (une seule fois) ───────────────────────────────────
# CSS avant </style>
html = html.replace('</style>', CSS + '\n</style>', 1)
# HTML avant </body>
html = html.replace('</body>', HTML_FAB + '\n</body>')
# JS avant dernier </script>
pos = html.rfind('</script>')
html = html[:pos] + JS + '\n</script>' + html[pos+9:]

# ── 6. Ajouter bouton 📐 dans les lignes appart (si pas encore là) ────────────
OLD_ACT = """<button class="btn btn-hide has-tip" onclick="blacklistToggle('${r.id}')" data-tip="Masquer temporairement — récupérable via le filtre &#39;Masqués&#39;">🙈</button>
      </td>"""
NEW_ACT = """<button class="btn btn-hide has-tip" onclick="blacklistToggle('${r.id}')" data-tip="Masquer temporairement — récupérable via le filtre &#39;Masqués&#39;">🙈</button>
        ${r.surface && r.price ? `<button class="btn-affiner has-tip" onclick="openEstimateur(${r.surface},${r.rooms||2},'${r.location||'Chamonix'}',${r.price})" data-tip="📐 Estimateur AVM — calcule le prix de marché et affiner avec état, vue, étage…">📐</button>` : ''}
      </td>"""
if OLD_ACT in html:
    html = html.replace(OLD_ACT, NEW_ACT, 1)
    print("Bouton 📐 ajouté dans actions")
else:
    print("Bouton 📐 déjà présent ou pattern non trouvé")

# ── 7. Sauvegarder ───────────────────────────────────────────────────────────
DASH.write_text(html, encoding="utf-8")
print(f"\nFinal: {len(html)//1024} KB")
print(f"  est-fab-btn: {html.count('est-fab-btn')} (attendu: 1)")
n_ov = html.count('id="est-overlay"')
print(f"  est-overlay: {n_ov} (attendu: 1)")
print(f"  function openEstimateur: {html.count('function openEstimateur(')} (attendu: 1)")
print(f"  AVM_LOOKUP: {html.count('AVM_LOOKUP')} (attendu: 2+ — const + référence)")
print("✅ Estimateur injecté proprement")
