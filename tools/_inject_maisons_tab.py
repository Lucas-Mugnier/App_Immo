# -*- coding: utf-8 -*-
"""Injecte l'onglet Maisons AVM dans dashboard.html"""
import sys, json, sqlite3
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

BASE = Path(__file__).parent
art  = json.load(open(BASE / 'dvf/avm_artifacts.json'))
tr   = json.load(open(BASE / 'dvf/terrain_ref_prix.json'))
qc   = json.load(open(BASE / 'dvf/qualitative_coeff.json'))
emp  = json.load(open(BASE / 'dvf/empirical_market_index.json'))
TE   = art['section_te_map']
EMP  = float(emp.get('2025', 1.185))

def ter_u(sec):
    r = tr.get(sec.upper(), tr['_GLOBAL'])
    return float(r.get('U') or tr['_GLOBAL']['U'])

# ── Extract maisons data ──────────────────────────────────────────────────
con = sqlite3.connect(BASE / 'dvf/listings_chamonix.db')
rows = con.execute("""
    SELECT id, url, titre, adresse_raw, section, surface, surf_terrain, pieces,
           prix, prix_initial, nb_baisses, historique_prix,
           avm_pred, avm_ratio, avm_score, first_seen, notes
    FROM maisons
    WHERE statut = 'actif' OR statut IS NULL
    ORDER BY avm_score DESC, prix ASC
""").fetchall()
con.close()
cols = ['id','url','titre','adresse_raw','section','surface','surf_terrain','pieces',
        'prix','prix_initial','nb_baisses','historique_prix',
        'avm_pred','avm_ratio','avm_score','first_seen','notes']

maisons = []
for row in rows:
    d = dict(zip(cols, row))
    try: d['historique_prix'] = json.loads(d['historique_prix'] or '[]')
    except: d['historique_prix'] = []
    if d['avm_pred']:  d['avm_pred']  = round(d['avm_pred'])
    if d['avm_ratio']: d['avm_ratio'] = round(d['avm_ratio'], 3)
    sec  = (d['section'] or 'G').upper()
    surf = d['surface']  or 100
    terr = d['surf_terrain'] or surf * 2.5
    vb = surf * TE.get(sec, 5000)
    vt = terr * ter_u(sec)
    d['terrain_ratio'] = round(vt / (vb + vt + 1), 3)
    maisons.append(d)

MAISONS_JS = json.dumps(maisons, ensure_ascii=False, separators=(',', ':'), default=str)
CALIB = {"A": 0.7098, "B": 0.7157, "C": 0.7311, "D": 0.6036, "E": 0.6612, "G": 0.6579}
SEC_LABELS = {'A':'La Tour','B':'Argentière','C':'Les Praz/Tines','D':'Centre est','E':'Les Bossons','G':'Moussoux'}

te_int  = {k: round(v) for k, v in TE.items()}
ter_ref = {k: round(ter_u(k)) for k in 'ABCDEG'}

# ── CSS ───────────────────────────────────────────────────────────────────
CSS = """
  /* ── Maisons AVM tab ── */
  .sec-badge{display:inline-block;width:22px;height:22px;border-radius:6px;font-size:.75rem;font-weight:700;line-height:22px;text-align:center;color:#fff;}
  .sec-A{background:#7c6f5e;}.sec-B{background:#3d7a5f;}.sec-C{background:#3d6a8a;}
  .sec-D{background:#7a3d5f;}.sec-E{background:#5f5f3d;}.sec-G{background:#7a5f3d;}
  .avm-range{font-size:.78rem;color:var(--muted);white-space:nowrap;}
  .ratio-badge{display:inline-block;padding:3px 8px;border-radius:10px;font-size:.8rem;font-weight:700;white-space:nowrap;}
  .ratio-great{background:var(--good-bg);color:var(--good);}
  .ratio-ok{background:#e8f0fd;color:#2855a0;}
  .ratio-mkt{background:var(--mid-bg);color:var(--mid);}
  .ratio-over{background:var(--bad-bg);color:var(--bad);}
  .btn-affiner{background:var(--accent);color:#fff;border:none;padding:5px 11px;border-radius:7px;cursor:pointer;font-size:.78rem;font-weight:600;white-space:nowrap;}
  .btn-affiner:hover{opacity:.85;}
  .modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9000;display:flex;align-items:center;justify-content:center;}
  .modal-box{background:var(--card);border-radius:14px;padding:26px 28px;max-width:500px;width:94vw;max-height:90vh;overflow-y:auto;box-shadow:0 8px 40px rgba(0,0,0,.25);}
  .modal-title{font-size:1.05rem;font-weight:700;color:var(--accent);margin:0 0 4px;}
  .modal-sub{font-size:.82rem;color:var(--muted);margin:0 0 18px;}
  .modal-sel-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;}
  .modal-sel-row.full{grid-template-columns:1fr;}
  .modal-label{font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:4px;}
  .modal-select{width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;font-size:.88rem;background:var(--bg);color:var(--text);}
  .avm-result-box{background:var(--bg);border-radius:10px;padding:16px;margin-top:16px;}
  .avm-central{font-size:1.6rem;font-weight:800;color:var(--accent);font-variant-numeric:tabular-nums;}
  .avm-fourchette{font-size:.82rem;color:var(--muted);margin-top:2px;}
  .avm-range-bar{position:relative;height:12px;background:#e8d8d8;border-radius:6px;margin:12px 0 4px;overflow:visible;}
  .avm-bar-fill{position:absolute;height:100%;border-radius:6px;background:linear-gradient(90deg,var(--good-bg),var(--good));}
  .avm-bar-prix{position:absolute;top:-5px;width:3px;height:22px;background:var(--bad);border-radius:2px;}
  .avm-bar-label{font-size:.7rem;color:var(--muted);display:flex;justify-content:space-between;}
  .avm-verdict{font-size:.85rem;font-weight:600;margin-top:10px;padding:8px 12px;border-radius:8px;}
  .avm-verdict.under{background:var(--good-bg);color:var(--good);}
  .avm-verdict.over{background:var(--bad-bg);color:var(--bad);}
  .avm-verdict.mkt{background:var(--mid-bg);color:var(--mid);}
  .avm-coeffs{font-size:.76rem;color:var(--muted);margin-top:8px;}
  .estim-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0;}
  .estim-form label{font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;display:block;margin-bottom:4px;}
  .estim-form input,.estim-form select{width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;font-size:.88rem;background:var(--bg);box-sizing:border-box;}
  .btn-estim{background:var(--accent);color:#fff;border:none;padding:10px 22px;border-radius:8px;cursor:pointer;font-size:.9rem;font-weight:600;margin-top:4px;}
  .estim-result-box{background:var(--bg);border-radius:10px;padding:18px;margin-top:14px;display:none;}
  .estim-central{font-size:1.8rem;font-weight:800;color:var(--accent);}"""

# ── HTML tab div ──────────────────────────────────────────────────────────
HTML_TAB = """
<div id="view-maisons" class="hidden">
<div id="maisons-stats" class="summary-bar" style="margin-bottom:12px"></div>
<div class="filters">
  <input id="m-search" placeholder="Rechercher (adresse, section...)" oninput="mFilter()">
  <select id="m-section" onchange="mFilter()">
    <option value="">Toutes sections</option>
    <option value="A">A — La Tour</option>
    <option value="B">B — Argentière</option>
    <option value="C">C — Les Praz / Tines</option>
    <option value="D">D — Centre est</option>
    <option value="E">E — Les Bossons</option>
    <option value="G">G — Moussoux</option>
  </select>
  <input id="m-maxprix" type="number" placeholder="Prix max (M€)" oninput="mFilter()" step="0.1">
  <select id="m-deal" onchange="mFilter()">
    <option value="">Tous les biens</option>
    <option value="under">AVM &gt; Prix (à saisir)</option>
    <option value="over">Prix &gt; AVM (surcôté)</option>
  </select>
</div>
<table style="margin-bottom:28px">
  <thead><tr>
    <th onclick="mSort('adresse_raw')">Localisation ↕</th>
    <th>Sect</th>
    <th onclick="mSort('surface')">Surface ↕</th>
    <th onclick="mSort('prix')">Prix demandé ↕</th>
    <th>AVM ± 18%</th>
    <th onclick="mSort('avm_ratio')">Ratio ↕</th>
    <th></th>
  </tr></thead>
  <tbody id="maisons-tbody"></tbody>
</table>

<div class="ins-card">
  <h2>🔧 Estimateur libre</h2>
  <p class="hint">Estimez n'importe quel bien Chamonix hors base — formule calibrée ±20%</p>
  <div class="estim-form">
    <div>
      <label>Section cadastrale</label>
      <select id="e-section">
        <option value="A">A — La Tour (1391m)</option>
        <option value="B" selected>B — Argentière (1222m)</option>
        <option value="C">C — Les Praz/Tines (1076m)</option>
        <option value="D">D — Centre est (1044m)</option>
        <option value="E">E — Les Bossons (1032m)</option>
        <option value="G">G — Moussoux (1062m)</option>
      </select>
    </div>
    <div>
      <label>Surface habitable (m²)</label>
      <input id="e-surface" type="number" placeholder="ex: 120" min="20" max="400">
    </div>
    <div>
      <label>Terrain (m²)</label>
      <input id="e-terrain" type="number" placeholder="ex: 500" min="0">
    </div>
    <div>
      <label>PLU zone</label>
      <select id="e-plu">
        <option value="U" selected>U — Constructible</option>
        <option value="N">N — Naturel</option>
        <option value="A">A — Agricole</option>
      </select>
    </div>
    <div>
      <label>État du bien</label>
      <select id="e-etat">
        <option value="cata">Inhabitable (×0.45)</option>
        <option value="renov">À rénover (×0.65)</option>
        <option value="moyen_r">Travaux partiels (×0.80)</option>
        <option value="moyen">Moyen (×0.90)</option>
        <option value="bon" selected>Bon état — réf. (×1.00)</option>
        <option value="tres_bon">Très bon (×1.13)</option>
        <option value="luxe">Luxe / Standing (×1.33)</option>
      </select>
    </div>
    <div>
      <label>Vue</label>
      <select id="e-vue">
        <option value="default" selected>Sans vue particulière</option>
        <option value="vue_massif">Vue massif (×1.12)</option>
        <option value="vue_mont_blanc">Vue Mont Blanc (×1.23)</option>
      </select>
    </div>
    <div>
      <label>Parking / Garage</label>
      <select id="e-parking">
        <option value="aucun" selected>Aucun</option>
        <option value="place_ext">Place extérieure (×1.01)</option>
        <option value="garage_simple">Garage simple (×1.03)</option>
        <option value="garage_double">Garage + parking (×1.05)</option>
      </select>
    </div>
    <div style="display:flex;align-items:flex-end">
      <button class="btn-estim" onclick="runEstim()">Estimer →</button>
    </div>
  </div>
  <div class="estim-result-box" id="estim-result">
    <div style="font-size:.8rem;color:var(--muted);margin-bottom:6px" id="estim-params"></div>
    <div class="estim-central" id="estim-central"></div>
    <div style="font-size:.85rem;color:var(--muted);margin:4px 0 12px" id="estim-range"></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:.82rem;margin-bottom:8px">
      <div id="estim-bati"></div><div id="estim-terrain"></div>
    </div>
    <div style="font-size:.74rem;color:var(--muted)">⚠️ Modèle XGBoost DVF, formule JS simplifiée ±20%. Fourchette ±18% calibrée LOO.</div>
  </div>
</div>
</div>

<!-- Modal Affiner -->
<div id="affiner-modal" class="modal-overlay hidden" onclick="if(event.target===this)closeAffiner()">
<div class="modal-box">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:2px">
    <div class="modal-title" id="aff-title">Affiner l'estimation</div>
    <button onclick="closeAffiner()" style="background:none;border:none;font-size:1.2rem;cursor:pointer;color:var(--muted);padding:0 4px">&#10005;</button>
  </div>
  <div class="modal-sub" id="aff-sub"></div>
  <div class="modal-sel-row">
    <div>
      <div class="modal-label">État du bien</div>
      <select class="modal-select" id="aff-etat" onchange="updateAffiner()">
        <option value="cata">Inhabitable (×0.45)</option>
        <option value="renov">À rénover (×0.65)</option>
        <option value="moyen_r">Travaux partiels (×0.80)</option>
        <option value="moyen">Moyen (×0.90)</option>
        <option value="bon" selected>Bon état (×1.00)</option>
        <option value="tres_bon">Très bon (×1.13)</option>
        <option value="luxe">Luxe / Standing (×1.33)</option>
      </select>
    </div>
    <div>
      <div class="modal-label">Vue</div>
      <select class="modal-select" id="aff-vue" onchange="updateAffiner()">
        <option value="default" selected>Sans vue</option>
        <option value="vue_massif">Vue massif (×1.12)</option>
        <option value="vue_mont_blanc">Vue Mont Blanc (×1.23)</option>
      </select>
    </div>
  </div>
  <div class="modal-sel-row full">
    <div>
      <div class="modal-label">Parking / Garage</div>
      <select class="modal-select" id="aff-parking" onchange="updateAffiner()">
        <option value="aucun" selected>Aucun</option>
        <option value="place_ext">Place extérieure (+1%)</option>
        <option value="garage_simple">Garage simple (+3%)</option>
        <option value="garage_double">Garage + parking (+5%)</option>
      </select>
    </div>
  </div>
  <div class="avm-result-box">
    <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Estimation corrigée</div>
    <div class="avm-central" id="aff-central">—</div>
    <div class="avm-fourchette" id="aff-range"></div>
    <div class="avm-range-bar" id="aff-bar-wrap">
      <div class="avm-bar-fill" id="aff-bar-fill"></div>
      <div class="avm-bar-prix" id="aff-bar-prix"></div>
    </div>
    <div class="avm-bar-label"><span id="aff-bar-lo"></span><span id="aff-bar-hi"></span></div>
    <div class="avm-verdict" id="aff-verdict"></div>
    <div class="avm-coeffs" id="aff-coeffs"></div>
  </div>
</div>
</div>"""

# ── JS ────────────────────────────────────────────────────────────────────
JS = (
    "\n// === MAISONS AVM ===\n"
    f"const MAISONS = {MAISONS_JS};\n"
    f"const SEC_LABELS_M = {json.dumps(SEC_LABELS, ensure_ascii=False)};\n"
    f"const TE_MAP_M = {json.dumps(te_int, ensure_ascii=False)};\n"
    f"const TER_U_M = {json.dumps(ter_ref, ensure_ascii=False)};\n"
    f"const EMP_IDX_M = {EMP};\n"
    f"const JS_CALIB_M = {json.dumps(CALIB, ensure_ascii=False)};\n"
    f"const Q_ETAT_M = {json.dumps(qc['etat'], ensure_ascii=False)};\n"
    f"const Q_VUE_M = {json.dumps(qc['vue'], ensure_ascii=False)};\n"
    f"const Q_PARK_M = {json.dumps(qc['parking'], ensure_ascii=False)};\n"
    "const FOURCHETTE_PCT = 0.18;\n"
    "\n"
    "function cEtatEff(c_raw,tr_ratio){return tr_ratio*1+(1-tr_ratio)*c_raw;}\n"
    "\n"
    "function applyQualit(avm,tr_ratio,etat,vue,parking,section){\n"
    "  const c_etat_raw=Q_ETAT_M[etat]||1;\n"
    "  const c_etat=cEtatEff(c_etat_raw,tr_ratio);\n"
    "  let c_vue=(vue==='vue_mont_blanc'&&section==='D')?(Q_VUE_M['vue_MB_section_D']||0.96):(Q_VUE_M[vue]||1);\n"
    "  const c_park=Q_PARK_M[parking]||1;\n"
    "  return {val:avm*c_etat*c_vue*c_park,c_etat,c_etat_raw,c_vue,c_park};\n"
    "}\n"
    "\n"
    "function jsEstimBase(section,surface,terrain,plu){\n"
    "  const te=TE_MAP_M[section]||5000,tu=TER_U_M[section]||623;\n"
    "  const surf_U=plu==='U'?terrain:0,surf_N=plu==='N'?terrain:0;\n"
    "  return (surface*te+surf_U*tu+surf_N*52)*EMP_IDX_M*(JS_CALIB_M[section]||0.676);\n"
    "}\n"
    "\n"
    "function ratioBadgM(ratio){\n"
    "  if(!ratio)return '<span class=\"ratio-badge\">—</span>';\n"
    "  const pct=Math.round((ratio-1)*100),sign=pct>=0?'+':'';\n"
    "  if(ratio>=1.15)return `<span class=\"ratio-badge ratio-great\">AVM ${sign}${pct}%</span>`;\n"
    "  if(ratio>=1.02)return `<span class=\"ratio-badge ratio-ok\">AVM ${sign}${pct}%</span>`;\n"
    "  if(ratio>=0.90)return `<span class=\"ratio-badge ratio-mkt\">AVM ${sign}${pct}%</span>`;\n"
    "  return `<span class=\"ratio-badge ratio-over\">AVM ${sign}${pct}%</span>`;\n"
    "}\n"
    "\n"
    "let mSortCol='avm_ratio',mSortAsc=false;\n"
    "function mSort(col){if(mSortCol===col)mSortAsc=!mSortAsc;else{mSortCol=col;mSortAsc=false;}mRender();}\n"
    "function mFilter(){mRender();}\n"
    "\n"
    "function mRender(){\n"
    "  const q=(document.getElementById('m-search').value||'').toLowerCase();\n"
    "  const sec=document.getElementById('m-section').value;\n"
    "  const maxP=parseFloat(document.getElementById('m-maxprix').value)*1e6||Infinity;\n"
    "  const deal=document.getElementById('m-deal').value;\n"
    "  let data=MAISONS.filter(m=>{\n"
    "    if(sec&&m.section!==sec)return false;\n"
    "    if(m.prix>maxP)return false;\n"
    "    if(deal==='under'&&(m.avm_ratio||0)<1)return false;\n"
    "    if(deal==='over'&&(m.avm_ratio||0)>=1)return false;\n"
    "    if(q){const hay=[m.adresse_raw,m.section,m.titre,m.notes].join(' ').toLowerCase();if(!hay.includes(q))return false;}\n"
    "    return true;\n"
    "  });\n"
    "  data.sort((a,b)=>{\n"
    "    let va=a[mSortCol],vb=b[mSortCol];\n"
    "    if(va==null)va=mSortAsc?Infinity:-Infinity;\n"
    "    if(vb==null)vb=mSortAsc?Infinity:-Infinity;\n"
    "    return mSortAsc?(va>vb?1:-1):(va<vb?1:-1);\n"
    "  });\n"
    "  const tbody=document.getElementById('maisons-tbody');\n"
    "  tbody.innerHTML=data.map(m=>{\n"
    "    const surf=m.surface?m.surface.toFixed(0)+'m²':'—';\n"
    "    const terr=m.surf_terrain?m.surf_terrain.toFixed(0)+'m²':'—';\n"
    "    const prix=m.prix?(m.prix/1e6).toFixed(3)+'M':'—';\n"
    "    const avm=m.avm_pred?(m.avm_pred/1e6).toFixed(3)+'M':'—';\n"
    "    const avmLo=m.avm_pred?((m.avm_pred*(1-FOURCHETTE_PCT))/1e6).toFixed(2):'—';\n"
    "    const avmHi=m.avm_pred?((m.avm_pred*(1+FOURCHETTE_PCT))/1e6).toFixed(2):'—';\n"
    "    const badge=ratioBadgM(m.avm_ratio);\n"
    "    const urlEl=m.url?`<a href=\"${m.url}\" target=\"_blank\">🔗</a>&nbsp;`:'';\n"
    "    const drop=m.nb_baisses>0?`<span class=\"badge badge-pos\">▼ ${m.nb_baisses} baisse${m.nb_baisses>1?'s':''}</span>`:'';\n"
    "    return `<tr>\n"
    "      <td>${urlEl}<strong>${m.adresse_raw||'—'}</strong>${drop}<br>\n"
    "        <span style=\"font-size:.74rem;color:var(--muted)\">${m.first_seen||''}</span></td>\n"
    "      <td><span class=\"sec-badge sec-${m.section}\">${m.section}</span>\n"
    "        <span style=\"font-size:.72rem;color:var(--muted);display:block;margin-top:2px\">${SEC_LABELS_M[m.section]||''}</span></td>\n"
    "      <td><strong>${surf}</strong><br><span class=\"avm-range\">${m.pieces||'—'}p &bull; ${terr}</span></td>\n"
    "      <td><strong>${prix}</strong></td>\n"
    "      <td><strong>${avm}</strong><br><span class=\"avm-range\">[${avmLo}&ndash;${avmHi}M]</span></td>\n"
    "      <td>${badge}</td>\n"
    "      <td><button class=\"btn-affiner\" onclick=\"openAffiner(${m.id})\">&#10022; Affiner</button></td>\n"
    "    </tr>`;\n"
    "  }).join('');\n"
    "  const sb=document.getElementById('maisons-stats');\n"
    "  const nb=data.length;\n"
    "  const nbUnder=data.filter(m=>(m.avm_ratio||0)>=1.02).length;\n"
    "  const med=data.filter(m=>m.prix).map(m=>m.prix).sort((a,b)=>a-b);\n"
    "  const medP=med.length?med[Math.floor(med.length/2)]:null;\n"
    "  sb.innerHTML=`<div class=\"stat-chip\"><strong>${nb}</strong> maisons</div>`\n"
    "    +`<div class=\"stat-chip\">AVM > Prix : <strong>${nbUnder}</strong></div>`\n"
    "    +(medP?`<div class=\"stat-chip\">Médiane <strong>${(medP/1e6).toFixed(2)}M€</strong></div>`:'')\n"
    "    +`<div class=\"stat-chip\">Précision modèle <strong>~20% LOO</strong></div>`;\n"
    "}\n"
    "\n"
    "let _affId=null;\n"
    "function openAffiner(id){\n"
    "  _affId=id;\n"
    "  const m=MAISONS.find(x=>x.id===id);\n"
    "  if(!m)return;\n"
    "  document.getElementById('aff-title').textContent=(m.adresse_raw||'Bien')+(m.section?' — Section '+m.section:'');\n"
    "  document.getElementById('aff-sub').textContent=[\n"
    "    m.surface?m.surface.toFixed(0)+'m² bâti':'',\n"
    "    m.surf_terrain?m.surf_terrain.toFixed(0)+'m² terrain':'',\n"
    "    m.pieces?m.pieces+'p':'',\n"
    "    m.prix?'Demandé '+(m.prix/1e6).toFixed(3)+'M€':''\n"
    "  ].filter(Boolean).join(' · ');\n"
    "  document.getElementById('aff-etat').value='bon';\n"
    "  document.getElementById('aff-vue').value='default';\n"
    "  document.getElementById('aff-parking').value='aucun';\n"
    "  document.getElementById('affiner-modal').classList.remove('hidden');\n"
    "  updateAffiner();\n"
    "}\n"
    "\n"
    "function closeAffiner(){document.getElementById('affiner-modal').classList.add('hidden');_affId=null;}\n"
    "\n"
    "function updateAffiner(){\n"
    "  const m=MAISONS.find(x=>x.id===_affId);\n"
    "  if(!m||!m.avm_pred)return;\n"
    "  const etat=document.getElementById('aff-etat').value;\n"
    "  const vue=document.getElementById('aff-vue').value;\n"
    "  const parking=document.getElementById('aff-parking').value;\n"
    "  const {val,c_etat,c_etat_raw,c_vue,c_park}=applyQualit(m.avm_pred,m.terrain_ratio||0.2,etat,vue,parking,m.section);\n"
    "  const lo=val*(1-FOURCHETTE_PCT),hi=val*(1+FOURCHETTE_PCT);\n"
    "  document.getElementById('aff-central').textContent=(val/1e6).toFixed(3)+' M€';\n"
    "  document.getElementById('aff-range').textContent='Fourchette : ['+(lo/1e6).toFixed(3)+' – '+(hi/1e6).toFixed(3)+' M€]';\n"
    "  if(m.prix){\n"
    "    const barMin=Math.min(lo*0.9,m.prix*0.9),barMax=Math.max(hi*1.1,m.prix*1.1);\n"
    "    const toX=v=>Math.max(0,Math.min(100,(v-barMin)/(barMax-barMin)*100));\n"
    "    const fl=toX(lo),fr=toX(hi);\n"
    "    document.getElementById('aff-bar-fill').style.left=fl+'%';\n"
    "    document.getElementById('aff-bar-fill').style.width=(fr-fl)+'%';\n"
    "    document.getElementById('aff-bar-prix').style.left=toX(m.prix)+'%';\n"
    "    document.getElementById('aff-bar-lo').textContent=(lo/1e6).toFixed(2)+'M';\n"
    "    document.getElementById('aff-bar-hi').textContent=(hi/1e6).toFixed(2)+'M';\n"
    "    const ratio=val/m.prix,pct=Math.round((ratio-1)*100),sign=pct>=0?'+':'';\n"
    "    const verd=document.getElementById('aff-verdict');\n"
    "    if(ratio>=1.15){verd.className='avm-verdict under';verd.textContent='✅ Bonne affaire — AVM '+sign+pct+'% vs prix demandé';}\n"
    "    else if(ratio>=1.02){verd.className='avm-verdict under';verd.textContent='📈 Légèrement sous-côté — AVM '+sign+pct+'%';}\n"
    "    else if(ratio>=0.92){verd.className='avm-verdict mkt';verd.textContent='⚖️ Prix marché — AVM '+sign+pct+'%';}\n"
    "    else{verd.className='avm-verdict over';verd.textContent='⚠️ Surcôté — AVM '+sign+pct+'% vs prix demandé';}\n"
    "    document.getElementById('aff-coeffs').textContent=\n"
    "      'Coeffs : état ×'+c_etat.toFixed(3)+' (brut ×'+c_etat_raw+', terrain '+Math.round((m.terrain_ratio||0)*100)+'%) · vue ×'+c_vue+' · parking ×'+c_park;\n"
    "  }\n"
    "}\n"
    "\n"
    "function runEstim(){\n"
    "  const sec=document.getElementById('e-section').value;\n"
    "  const surface=parseFloat(document.getElementById('e-surface').value);\n"
    "  const terrain=parseFloat(document.getElementById('e-terrain').value)||surface*2.5;\n"
    "  const plu=document.getElementById('e-plu').value;\n"
    "  const etat=document.getElementById('e-etat').value;\n"
    "  const vue=document.getElementById('e-vue').value;\n"
    "  const parking=document.getElementById('e-parking').value;\n"
    "  if(!surface||surface<20){alert('Surface requise (min 20m²)');return;}\n"
    "  const base=jsEstimBase(sec,surface,terrain,plu);\n"
    "  const te=TE_MAP_M[sec]||5000,tu=TER_U_M[sec]||623;\n"
    "  const surf_U=plu==='U'?terrain:0;\n"
    "  const vb=surface*te,vt=surf_U*tu;\n"
    "  const tr_ratio=vt/(vb+vt+1);\n"
    "  const {val}=applyQualit(base,tr_ratio,etat,vue,parking,sec);\n"
    "  const lo=val*(1-FOURCHETTE_PCT),hi=val*(1+FOURCHETTE_PCT);\n"
    "  document.getElementById('estim-params').textContent='Section '+sec+' ('+SEC_LABELS_M[sec]+') · '+surface+'m² bâti · '+terrain.toFixed(0)+'m² terrain '+plu;\n"
    "  document.getElementById('estim-central').textContent=(val/1e6).toFixed(3)+' M€';\n"
    "  document.getElementById('estim-range').textContent='Fourchette ±18% : ['+(lo/1e6).toFixed(3)+' – '+(hi/1e6).toFixed(3)+' M€]';\n"
    "  const calib=JS_CALIB_M[sec]||0.676;\n"
    "  document.getElementById('estim-bati').innerHTML='<strong>Part bâtie</strong><br>~'+(vb*EMP_IDX_M*calib/1e3).toFixed(0)+'k€ indicatif';\n"
    "  document.getElementById('estim-terrain').innerHTML='<strong>Part terrain ('+plu+')</strong><br>~'+(vt/1e3).toFixed(0)+'k€ indicatif';\n"
    "  document.getElementById('estim-result').style.display='block';\n"
    "}\n"
    "\n"
    "mRender();\n"
)

# ── Inject into dashboard.html ────────────────────────────────────────────
html = Path(BASE / 'dashboard.html').read_text(encoding='utf-8')

# Guard: don't double-inject
if 'view-maisons' in html:
    print("Déjà injecté — nettoyage d'abord")
    # Simple approach: re-run clean version
    # For now just exit with warning
    print("ATTENTION: view-maisons déjà présent. Supprimer manuellement et relancer.")
    sys.exit(1)

# 1. Tab button
html = html.replace(
    "<button class=\"tab\" id=\"tab-simulation\" onclick=\"showTab('simulation')\">🧮 Simulation</button>",
    "<button class=\"tab\" id=\"tab-simulation\" onclick=\"showTab('simulation')\">🧮 Simulation</button>\n  <button class=\"tab\" id=\"tab-maisons\" onclick=\"showTab('maisons')\">🏠 Maisons AVM</button>"
)

# 2. CSS
html = html.replace('</style>', CSS + '\n</style>')

# 3. TABS array
html = html.replace(
    "const TABS = ['listings','insights','comparateur','simulation'];",
    "const TABS = ['listings','insights','comparateur','simulation','maisons'];"
)

# 4. HTML div before </body>
html = html.replace('</body>', HTML_TAB + '\n</body>')

# 5. JS before closing </script>
html = html.replace(
    "sort('score');\nrender();\nbuildSummaryBar();\n</script>",
    "sort('score');\nrender();\nbuildSummaryBar();\n" + JS + "</script>"
)

Path(BASE / 'dashboard.html').write_text(html, encoding='utf-8')
size_kb = len(html) // 1024
print(f"OK — dashboard.html mis à jour ({size_kb} KB)")
print(f"  {len(maisons)} maisons injectées")
print(f"  Sections: {set(m['section'] for m in maisons)}")
