# -*- coding: utf-8 -*-
"""Génère carte_chamonix.html — carte cadastrale + DVF + estimateur"""
import sys, json, sqlite3, csv, collections
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

BASE = Path(__file__).parent

# ── Data loading ──────────────────────────────────────────────────────────
pts      = json.load(open(BASE / 'dvf/dvf_chamonix_points.json'))
cadastre = json.load(open(BASE / 'dvf/cadastre_sections_74056.json'))
art      = json.load(open(BASE / 'dvf/avm_artifacts.json'))
tr_ref   = json.load(open(BASE / 'dvf/terrain_ref_prix.json'))
qc       = json.load(open(BASE / 'dvf/qualitative_coeff.json'))
emp_j    = json.load(open(BASE / 'dvf/empirical_market_index.json'))
EMP      = float(emp_j.get('2025', 1.185))
TE       = art['section_te_map']

def ter_u(sec):
    r = tr_ref.get(sec.upper(), tr_ref['_GLOBAL'])
    return float(r.get('U') or tr_ref['_GLOBAL']['U'])

con = sqlite3.connect(BASE / 'dvf/listings_chamonix.db')
listings_raw = con.execute(
    "SELECT id, url, adresse_raw, section, surface, surf_terrain, pieces,"
    "prix, avm_pred, avm_ratio, avm_score, nb_baisses "
    "FROM maisons WHERE statut='actif' OR statut IS NULL"
).fetchall()
con.close()

listings = []
for r in listings_raw:
    listings.append({
        'id': r[0], 'url': r[1], 'addr': r[2], 'sec': r[3],
        'surf': r[4], 'terr': r[5], 'pcs': r[6], 'prix': r[7],
        'avm': round(r[8]) if r[8] else None,
        'ratio': round(r[9], 3) if r[9] else None,
        'score': r[10], 'baisses': r[11]
    })

# Section metadata
SEC_INFO = {
    'A': {'label': 'La Tour',        'med': 1.18, 'n': 9,  'alt': 1391},
    'B': {'label': 'Argentière',     'med': 1.22, 'n': 35, 'alt': 1222},
    'C': {'label': 'Les Praz/Tines', 'med': 1.90, 'n': 89, 'alt': 1076},
    'D': {'label': 'Centre est',     'med': 1.34, 'n': 58, 'alt': 1044},
    'E': {'label': 'Les Bossons',    'med': 0.80, 'n': 46, 'alt': 1032},
    'F': {'label': 'Hors modèle',    'med': None, 'n': 0,  'alt': None},
    'G': {'label': 'Moussoux',       'med': 2.00, 'n': 72, 'alt': 1062},
    'H': {'label': 'Hors modèle',    'med': None, 'n': 0,  'alt': None},
}

# Price → color scale (choropleth 0.8M–2.0M)
def price_color(med):
    if med is None: return '#e0e0e0'
    bins = [0.9, 1.2, 1.5, 1.8, 2.1]
    colors = ['#c8e6c9','#a5d6a7','#ffcc80','#ff8a65','#e53935']
    for i, b in enumerate(bins):
        if med <= b: return colors[i]
    return colors[-1]

# Calibration
CALIB = {"A": 0.7098, "B": 0.7157, "C": 0.7311, "D": 0.6036, "E": 0.6612, "G": 0.6579}

TE_INT  = {k: round(v) for k, v in TE.items()}
TER_REF = {k: round(ter_u(k)) for k in 'ABCDEG'}

CADASTRE_JS  = json.dumps(cadastre, ensure_ascii=False, separators=(',', ':'))
LISTINGS_JS  = json.dumps(listings, ensure_ascii=False, separators=(',', ':'))
DVF_PTS_JS   = json.dumps(pts,     ensure_ascii=False, separators=(',', ':'))
SEC_INFO_JS  = json.dumps(SEC_INFO, ensure_ascii=False, separators=(',', ':'))
Q_ETAT_JS    = json.dumps(qc['etat'],    ensure_ascii=False, separators=(',', ':'))
Q_VUE_JS     = json.dumps(qc['vue'],     ensure_ascii=False, separators=(',', ':'))
Q_PARK_JS    = json.dumps(qc['parking'], ensure_ascii=False, separators=(',', ':'))
TE_JS        = json.dumps(TE_INT,  ensure_ascii=False, separators=(',', ':'))
TER_JS       = json.dumps(TER_REF, ensure_ascii=False, separators=(',', ':'))
CALIB_JS     = json.dumps(CALIB,   ensure_ascii=False, separators=(',', ':'))

# Section fill colors
sec_colors = {s: price_color(SEC_INFO[s]['med']) for s in SEC_INFO}

HTML = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carte AVM Chamonix</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  :root{{--bg:#fbeeee;--card:#fff;--text:#1a1212;--muted:#7a6b6b;--accent:#2b453e;
        --border:#e8d8d8;--good:#2b8c70;--good-bg:#e6f5f0;--bad:#b84040;--bad-bg:#fde8e8;
        --mid:#b07a20;--mid-bg:#fdf3e0}}
  body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column}}
  header{{background:var(--accent);color:#fff;padding:12px 20px;display:flex;align-items:center;gap:16px;flex-shrink:0}}
  header h1{{font-size:1.1rem;font-weight:700}}
  header .back{{color:rgba(255,255,255,.7);font-size:.85rem;text-decoration:none}}
  header .back:hover{{color:#fff}}
  .main{{display:flex;flex:1;overflow:hidden}}
  #map{{flex:1;min-width:0}}
  .panel{{width:380px;flex-shrink:0;background:var(--card);border-left:1px solid var(--border);overflow-y:auto;display:flex;flex-direction:column}}
  .panel-head{{padding:16px 18px;border-bottom:1px solid var(--border);background:#f8f3ef}}
  .panel-head h2{{font-size:.95rem;color:var(--accent);font-weight:700;margin-bottom:2px}}
  .panel-head p{{font-size:.78rem;color:var(--muted)}}
  .panel-body{{padding:16px 18px;flex:1}}
  .sec-hero{{background:var(--accent);color:#fff;border-radius:10px;padding:14px 16px;margin-bottom:16px;display:none}}
  .sec-hero .sec-code{{font-size:2rem;font-weight:800;line-height:1}}
  .sec-hero .sec-name{{font-size:.95rem;opacity:.85;margin-top:2px}}
  .sec-hero .sec-stats{{font-size:.78rem;opacity:.7;margin-top:6px}}
  .form-row{{margin-bottom:10px}}
  .form-row label{{font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;display:block;margin-bottom:4px}}
  .form-row input,.form-row select{{width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;font-size:.88rem;background:var(--bg);color:var(--text)}}
  .form-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}}
  .btn-estim{{width:100%;background:var(--accent);color:#fff;border:none;padding:11px;border-radius:9px;font-size:.95rem;font-weight:700;cursor:pointer;margin-top:4px}}
  .btn-estim:hover{{opacity:.88}}
  .result-box{{background:var(--bg);border-radius:10px;padding:14px 16px;margin-top:14px;display:none}}
  .result-val{{font-size:1.7rem;font-weight:800;color:var(--accent);font-variant-numeric:tabular-nums}}
  .result-range{{font-size:.82rem;color:var(--muted);margin:3px 0 10px}}
  .result-row{{display:flex;justify-content:space-between;font-size:.8rem;padding:4px 0;border-top:1px solid var(--border)}}
  .result-label{{color:var(--muted)}}
  .result-val2{{font-weight:600}}
  .toggle-bar{{display:flex;gap:6px;padding:10px 18px;border-bottom:1px solid var(--border);background:#f8f3ef;flex-wrap:wrap}}
  .toggle-btn{{border:1px solid var(--border);background:var(--card);padding:4px 10px;border-radius:12px;cursor:pointer;font-size:.77rem;color:var(--text);font-weight:600}}
  .toggle-btn.on{{background:var(--accent);color:#fff;border-color:var(--accent)}}
  /* Legend */
  .legend{{position:absolute;bottom:26px;left:10px;z-index:1000;background:rgba(255,255,255,.93);border-radius:10px;padding:10px 14px;box-shadow:0 2px 10px rgba(0,0,0,.15);font-size:.75rem}}
  .legend h4{{font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin-bottom:6px}}
  .leg-row{{display:flex;align-items:center;gap:6px;margin-bottom:3px}}
  .leg-dot{{width:14px;height:14px;border-radius:3px;flex-shrink:0}}
  /* Info popup */
  .listing-popup{{font-size:.82rem;line-height:1.5;min-width:180px}}
  .listing-popup strong{{color:var(--accent)}}
  .ratio-chip{{display:inline-block;padding:2px 7px;border-radius:8px;font-weight:700;font-size:.75rem}}
</style>
</head>
<body>
<header>
  <a class="back" href="dashboard.html">← Dashboard</a>
  <h1>🗺️ Carte AVM Chamonix — Sections Cadastrales</h1>
  <span style="font-size:.8rem;opacity:.7;margin-left:auto">Cliquez une section pour estimer</span>
</header>
<div class="toggle-bar">
  <button class="toggle-btn on"  id="btn-sections" onclick="toggleLayer('sections')">📐 Sections</button>
  <button class="toggle-btn on"  id="btn-dvf"      onclick="toggleLayer('dvf')">💰 DVF transact.</button>
  <button class="toggle-btn on"  id="btn-listings"  onclick="toggleLayer('listings')">🏠 Biens à vendre</button>
</div>
<div class="main">
  <div id="map"></div>
  <div class="panel">
    <div class="panel-head">
      <h2>Estimateur AVM</h2>
      <p>Cliquez une section sur la carte ou sélectionnez manuellement</p>
    </div>
    <div class="panel-body">
      <div class="sec-hero" id="sec-hero">
        <div class="sec-code" id="sec-hero-code">D</div>
        <div class="sec-name" id="sec-hero-name">Centre est</div>
        <div class="sec-stats" id="sec-hero-stats"></div>
      </div>
      <div class="form-row">
        <label>Section cadastrale</label>
        <select id="e-sec" onchange="onSecChange()">
          <option value="">— Cliquez la carte ou choisissez —</option>
          <option value="A">A — La Tour (1391m)</option>
          <option value="B">B — Argentière (1222m)</option>
          <option value="C">C — Les Praz / Tines (1076m)</option>
          <option value="D">D — Centre est (1044m)</option>
          <option value="E">E — Les Bossons (1032m)</option>
          <option value="G">G — Moussoux (1062m)</option>
        </select>
      </div>
      <div class="form-grid">
        <div class="form-row">
          <label>Surface bâtie (m²)</label>
          <input id="e-surf" type="number" placeholder="ex: 120" min="20" max="400">
        </div>
        <div class="form-row">
          <label>Terrain (m²)</label>
          <input id="e-terr" type="number" placeholder="ex: 500" min="0">
        </div>
      </div>
      <div class="form-grid">
        <div class="form-row">
          <label>PLU zone</label>
          <select id="e-plu">
            <option value="U" selected>U — Constructible</option>
            <option value="N">N — Naturel</option>
            <option value="A">A — Agricole</option>
          </select>
        </div>
        <div class="form-row">
          <label>État du bien</label>
          <select id="e-etat">
            <option value="cata">Inhabitable (×0.45)</option>
            <option value="renov">À rénover (×0.65)</option>
            <option value="moyen_r">Trav. partiels (×0.80)</option>
            <option value="moyen">Moyen (×0.90)</option>
            <option value="bon" selected>Bon état (×1.00)</option>
            <option value="tres_bon">Très bon (×1.13)</option>
            <option value="luxe">Luxe (×1.33)</option>
          </select>
        </div>
      </div>
      <div class="form-grid">
        <div class="form-row">
          <label>Vue</label>
          <select id="e-vue">
            <option value="default" selected>Sans vue</option>
            <option value="vue_massif">Vue massif (×1.12)</option>
            <option value="vue_mont_blanc">Vue Mont Blanc (×1.23)</option>
          </select>
        </div>
        <div class="form-row">
          <label>Parking / Garage</label>
          <select id="e-park">
            <option value="aucun" selected>Aucun</option>
            <option value="place_ext">Place ext. (+1%)</option>
            <option value="garage_simple">Garage (+3%)</option>
            <option value="garage_double">Garage+parking (+5%)</option>
          </select>
        </div>
      </div>
      <button class="btn-estim" onclick="runEstim()">Estimer ce bien →</button>
      <div class="result-box" id="result-box">
        <div style="font-size:.72rem;color:var(--muted);margin-bottom:4px" id="result-params"></div>
        <div class="result-val" id="result-val"></div>
        <div class="result-range" id="result-range"></div>
        <div class="result-row"><span class="result-label">Part bâtie indicative</span><span class="result-val2" id="result-bati"></span></div>
        <div class="result-row"><span class="result-label">Part terrain indicative</span><span class="result-val2" id="result-terr"></span></div>
        <div class="result-row"><span class="result-label">Prix/m² implicite</span><span class="result-val2" id="result-pm2"></span></div>
        <div style="font-size:.71rem;color:var(--muted);margin-top:8px">⚠️ Formule JS calibrée ±20% — fourchette ±18% LOO calibrée</div>
      </div>
    </div>
  </div>
</div>

<script>
// ── Data ─────────────────────────────────────────────────────────────────
const CADASTRE  = {CADASTRE_JS};
const LISTINGS  = {LISTINGS_JS};
const DVF_PTS   = {DVF_PTS_JS};
const SEC_INFO  = {SEC_INFO_JS};
const Q_ETAT    = {Q_ETAT_JS};
const Q_VUE     = {Q_VUE_JS};
const Q_PARK    = {Q_PARK_JS};
const TE_MAP    = {TE_JS};
const TER_U_MAP = {TER_JS};
const CALIB     = {CALIB_JS};
const EMP_IDX   = {EMP};
const FOURCHpct = 0.18;

const SEC_COLORS = {{
  A:'#c8e6c9', B:'#c8e6c9', C:'#ffcc80', D:'#a5d6a7',
  E:'#c8e6c9', F:'#e0e0e0', G:'#ff8a65', H:'#e0e0e0'
}};

// ── Map init ──────────────────────────────────────────────────────────────
const map = L.map('map').setView([45.930, 6.870], 13);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap', maxZoom: 18
}}).addTo(map);

// ── Layers ────────────────────────────────────────────────────────────────
const layerSections = L.layerGroup().addTo(map);
const layerDVF      = L.layerGroup().addTo(map);
const layerListings = L.layerGroup().addTo(map);

const layerState = {{sections:true, dvf:true, listings:true}};
function toggleLayer(name) {{
  layerState[name] = !layerState[name];
  const layer = {{sections:layerSections,dvf:layerDVF,listings:layerListings}}[name];
  if (layerState[name]) map.addLayer(layer);
  else map.removeLayer(layer);
  document.getElementById('btn-'+name).classList.toggle('on', layerState[name]);
}}

// ── Section polygons ──────────────────────────────────────────────────────
let selectedSec = null;
const sectionLayers = {{}};

CADASTRE.features.forEach(f => {{
  const code = (f.properties.prefixe || '') + (f.properties.code || f.properties.section || '');
  const sec  = code.replace(/^0+/,'').toUpperCase();
  const info = SEC_INFO[sec] || {{}};
  const color = SEC_COLORS[sec] || '#e0e0e0';
  const hasModel = ['A','B','C','D','E','G'].includes(sec);

  const layer = L.geoJSON(f, {{
    style: {{
      fillColor: color, fillOpacity: 0.55,
      color: '#555', weight: 1.5, opacity: 0.8
    }}
  }});

  layer.on('click', () => {{
    if (!hasModel) return;
    selectSection(sec);
    // Zoom to section
    map.fitBounds(layer.getBounds(), {{padding:[20,20]}});
  }});

  layer.on('mouseover', e => {{
    e.target.setStyle({{fillOpacity:0.8, weight:2.5}});
    const med = info.med ? info.med.toFixed(2)+'M€' : 'Hors modèle';
    layer.bindTooltip(
      `<strong>Section ${{sec}}</strong> — ${{info.label||'?'}}<br>` +
      `Médiane DVF : ${{med}} (${{info.n||0}} transact.)` +
      (hasModel ? '' : '<br><em>Pas dans le modèle</em>'),
      {{sticky:true}}
    ).openTooltip(e.latlng);
  }});
  layer.on('mouseout', e => {{
    e.target.setStyle({{fillOpacity:0.55, weight:1.5}});
    layer.closeTooltip();
  }});

  sectionLayers[sec] = layer;
  layer.addTo(layerSections);
}});

function selectSection(sec) {{
  selectedSec = sec;
  // Reset all styles
  Object.entries(sectionLayers).forEach(([s,l]) => {{
    l.setStyle({{fillColor:SEC_COLORS[s]||'#e0e0e0', fillOpacity:0.55, weight:1.5}});
  }});
  // Highlight selected
  if (sectionLayers[sec]) {{
    sectionLayers[sec].setStyle({{fillOpacity:0.85, weight:3, color:'#2b453e'}});
  }}
  // Update dropdown
  document.getElementById('e-sec').value = sec;
  // Update hero
  const info = SEC_INFO[sec] || {{}};
  document.getElementById('sec-hero').style.display = 'block';
  document.getElementById('sec-hero-code').textContent = sec;
  document.getElementById('sec-hero-name').textContent = info.label || sec;
  const med = info.med ? info.med.toFixed(2)+'M€' : '—';
  document.getElementById('sec-hero-stats').textContent =
    `Médiane DVF : ${{med}} · ${{info.n||0}} transactions · Alt. ${{info.alt||'—'}}m`;
}}

function onSecChange() {{
  const sec = document.getElementById('e-sec').value;
  if (sec) selectSection(sec);
}}

// ── DVF heatmap circles ───────────────────────────────────────────────────
DVF_PTS.forEach(p => {{
  const r = L.circleMarker([p.lat, p.lon], {{
    radius: 5, fillColor: priceColor(p.prix),
    color: 'rgba(0,0,0,0.3)', weight: 0.5, fillOpacity: 0.75
  }});
  r.bindTooltip(`${{(p.prix/1e6).toFixed(2)}}M€ · Section ${{p.sec}} · ${{p.annee}}`);
  r.addTo(layerDVF);
}});

function priceColor(prix) {{
  if (prix < 600000)  return '#4caf50';
  if (prix < 1200000) return '#8bc34a';
  if (prix < 1800000) return '#ff9800';
  if (prix < 2800000) return '#ff5722';
  return '#b71c1c';
}}

// ── Listings markers (centroïde section) ─────────────────────────────────
// Centroids approximatifs par section
const SEC_CENTROIDS = {{
  A:[45.993, 6.939], B:[45.976, 6.921], C:[45.945, 6.900],
  D:[45.924, 6.871], E:[45.896, 6.852], G:[45.920, 6.855]
}};

// Group listings by section
const bySec = {{}};
LISTINGS.forEach(m => {{
  if (!m.sec) return;
  if (!bySec[m.sec]) bySec[m.sec] = [];
  bySec[m.sec].push(m);
}});

Object.entries(bySec).forEach(([sec, items]) => {{
  const center = SEC_CENTROIDS[sec];
  if (!center) return;
  const n = items.length;
  const avgRatio = items.filter(m=>m.ratio).reduce((s,m)=>s+m.ratio,0) / (items.filter(m=>m.ratio).length||1);
  const col = avgRatio >= 1.1 ? '#2b8c70' : avgRatio >= 0.95 ? '#b07a20' : '#b84040';

  const marker = L.circleMarker(center, {{
    radius: 10 + Math.sqrt(n)*2,
    fillColor: col, color: '#fff', weight: 2,
    fillOpacity: 0.85
  }});

  let popup = `<div class="listing-popup"><strong>Section ${{sec}} — ${{SEC_INFO[sec]?.label||''}}</strong><br>` +
    `${{n}} bien${{n>1?'s':''}} à vendre · ratio AVM moy. ${{avgRatio.toFixed(2)}}<hr style="margin:6px 0">`;
  items.slice(0,8).forEach(m => {{
    const prix = m.prix ? (m.prix/1e6).toFixed(2)+'M' : '—';
    const avm  = m.avm  ? (m.avm/1e6).toFixed(2)+'M'  : '—';
    const rat  = m.ratio ? m.ratio : 0;
    const chip = rat >= 1.1
      ? `<span class="ratio-chip" style="background:#e6f5f0;color:#2b8c70">AVM +${{Math.round((rat-1)*100)}}%</span>`
      : rat >= 0.95
      ? `<span class="ratio-chip" style="background:#fdf3e0;color:#b07a20">±${{Math.round((rat-1)*100)}}%</span>`
      : `<span class="ratio-chip" style="background:#fde8e8;color:#b84040">${{Math.round((rat-1)*100)}}%</span>`;
    popup += `<div style="padding:3px 0;border-bottom:1px solid #f0e0e0">
      ${{m.addr||'—'}} · ${{m.surf||'?'}}m² · ${{prix}}
      ${{chip}}${{m.url ? ' <a href="'+m.url+'" target="_blank">🔗</a>' : ''}}
    </div>`;
  }});
  if (n > 8) popup += `<div style="color:var(--muted);font-size:.74rem">+ ${{n-8}} autres</div>`;
  popup += '</div>';
  marker.bindPopup(popup, {{maxWidth:300}});

  marker.on('click', () => selectSection(sec));
  marker.addTo(layerListings);
}});

// ── Legend ────────────────────────────────────────────────────────────────
const legend = L.control({{position:'bottomleft'}});
legend.onAdd = () => {{
  const div = L.DomUtil.create('div','legend');
  div.innerHTML = `
    <h4>Prix DVF transact.</h4>
    <div class="leg-row"><div class="leg-dot" style="background:#4caf50"></div>< 600k€</div>
    <div class="leg-row"><div class="leg-dot" style="background:#8bc34a"></div>600k – 1.2M</div>
    <div class="leg-row"><div class="leg-dot" style="background:#ff9800"></div>1.2M – 1.8M</div>
    <div class="leg-row"><div class="leg-dot" style="background:#ff5722"></div>1.8M – 2.8M</div>
    <div class="leg-row"><div class="leg-dot" style="background:#b71c1c"></div>> 2.8M</div>
    <h4 style="margin-top:8px">Biens à vendre</h4>
    <div class="leg-row"><div class="leg-dot" style="background:#2b8c70;border-radius:50%"></div>AVM > Prix</div>
    <div class="leg-row"><div class="leg-dot" style="background:#b07a20;border-radius:50%"></div>Prix marché</div>
    <div class="leg-row"><div class="leg-dot" style="background:#b84040;border-radius:50%"></div>Surcôté</div>`;
  return div;
}};
legend.addTo(map);

// ── Estimateur ────────────────────────────────────────────────────────────
function cEtatEff(c_raw, tr_ratio) {{ return tr_ratio + (1 - tr_ratio) * c_raw; }}

function runEstim() {{
  const sec     = document.getElementById('e-sec').value;
  const surface = parseFloat(document.getElementById('e-surf').value);
  const terrain = parseFloat(document.getElementById('e-terr').value) || surface * 2.5;
  const plu     = document.getElementById('e-plu').value;
  const etat    = document.getElementById('e-etat').value;
  const vue     = document.getElementById('e-vue').value;
  const park    = document.getElementById('e-park').value;

  if (!sec) {{ alert('Cliquez une section sur la carte'); return; }}
  if (!surface || surface < 20) {{ alert('Surface requise (min 20m²)'); return; }}

  const te   = TE_MAP[sec] || 5000;
  const tu   = TER_U_MAP[sec] || 623;
  const surf_U = plu === 'U' ? terrain : 0;
  const surf_N = plu === 'N' ? terrain : 0;
  const vb = surface * te;
  const vt = surf_U * tu + surf_N * 52;
  const calib = CALIB[sec] || 0.676;
  const base = (vb + vt) * EMP_IDX * calib;

  const c_etat_raw = Q_ETAT[etat] || 1;
  const tr_ratio   = vt / (vb + vt + 1);
  const c_etat     = cEtatEff(c_etat_raw, tr_ratio);
  let   c_vue      = (vue === 'vue_mont_blanc' && sec === 'D')
                     ? (Q_VUE['vue_MB_section_D'] || 0.96) : (Q_VUE[vue] || 1);
  const c_park     = Q_PARK[park] || 1;
  const val = base * c_etat * c_vue * c_park;
  const lo  = val * (1 - FOURCHpct), hi = val * (1 + FOURCHpct);

  document.getElementById('result-params').textContent =
    `Section ${{sec}} (${{SEC_INFO[sec]?.label}}) · ${{surface}}m² · ${{terrain.toFixed(0)}}m² terr. ${{plu}}`;
  document.getElementById('result-val').textContent   = (val/1e6).toFixed(3) + ' M€';
  document.getElementById('result-range').textContent = `[${{(lo/1e6).toFixed(3)}} – ${{(hi/1e6).toFixed(3)}} M€]  ±18%`;
  document.getElementById('result-bati').textContent  = '~' + (vb*EMP_IDX*calib/1e3).toFixed(0) + 'k€';
  document.getElementById('result-terr').textContent  = '~' + (vt*EMP_IDX*calib/1e3).toFixed(0) + 'k€';
  document.getElementById('result-pm2').textContent   = Math.round(val/surface).toLocaleString('fr-FR') + ' €/m²';
  document.getElementById('result-box').style.display = 'block';
}}
</script>
</body>
</html>"""

Path(BASE / 'carte_chamonix.html').write_text(HTML, encoding='utf-8')
size = len(HTML) // 1024
print(f"OK — carte_chamonix.html ({size}KB)")
print(f"  Sections cadastrales : {len(cadastre['features'])}")
print(f"  Points DVF : {len(pts)}")
print(f"  Listings DB : {len(listings)}")
