"""
_inject_insights_v2.py
======================
Injecte le tab Insights v2 dans dashboard.html :
- Filter Tous / Apparts / Maisons
- KPI row dynamique
- Distribution ratios AVM (bar chart CSS)
- Scatter Prix vs AVM (SVG)
- PM2 histogram comparatif
- Top 8 opportunités
"""
import re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
DASH = BASE / "dashboard.html"
html = DASH.read_text(encoding="utf-8")

# ─── CSS ──────────────────────────────────────────────────────────────────────
CSS = """
/* ── Insights v2 ── */
.ins-filter-row{display:flex;gap:8px;margin-bottom:18px;flex-wrap:wrap;align-items:center;}
.ins-type-btn{padding:7px 18px;border:2px solid var(--border);border-radius:20px;background:var(--card);
  cursor:pointer;font-size:.85rem;font-weight:600;color:var(--muted);transition:all .15s;}
.ins-type-btn.active{border-color:var(--accent);background:var(--accent);color:#fff;}
.ins-kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:20px;}
.ins-kpi{background:var(--card);border-radius:10px;padding:14px 16px;text-align:center;
  box-shadow:0 1px 6px rgba(0,0,0,.07);border:1px solid var(--border);}
.ins-kpi-val{font-size:1.5rem;font-weight:800;color:var(--accent);line-height:1;}
.ins-kpi-lbl{font-size:.72rem;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.04em;}
.ins-kpi-sub{font-size:.7rem;color:var(--muted);margin-top:2px;}
.ins-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}
@media(max-width:700px){.ins-grid-2{grid-template-columns:1fr;}}
.ins-card{background:var(--card);border-radius:12px;padding:18px 20px;
  box-shadow:0 1px 8px rgba(0,0,0,.07);border:1px solid var(--border);}
.ins-card h3{font-size:.9rem;font-weight:700;color:var(--text);margin:0 0 14px;
  text-transform:uppercase;letter-spacing:.05em;}
/* AVM ratio bar chart */
.ratio-bar-row{display:flex;align-items:center;gap:8px;margin-bottom:7px;font-size:.8rem;}
.ratio-bar-label{width:130px;flex-shrink:0;color:var(--text);font-weight:500;text-align:right;}
.ratio-bar-track{flex:1;background:var(--bg);border-radius:4px;height:20px;overflow:hidden;position:relative;}
.ratio-bar-fill{height:100%;border-radius:4px;transition:width .4s ease;display:flex;align-items:center;padding-left:6px;}
.ratio-bar-fill span{font-size:.72rem;font-weight:700;color:#fff;white-space:nowrap;}
.ratio-bar-count{width:28px;flex-shrink:0;text-align:right;color:var(--muted);font-size:.75rem;font-weight:600;}
/* PM2 histogram */
.pm2-hist-wrap{display:flex;flex-direction:column;gap:5px;}
.pm2-hist-row{display:flex;align-items:center;gap:6px;font-size:.75rem;}
.pm2-hist-lbl{width:80px;flex-shrink:0;color:var(--muted);text-align:right;}
.pm2-hist-bars{flex:1;display:flex;flex-direction:column;gap:2px;}
.pm2-hist-bar{height:10px;border-radius:3px;min-width:2px;transition:width .3s;}
/* Scatter SVG */
#ins-scatter{width:100%;height:280px;}
/* Top table */
.ins-top-table{width:100%;border-collapse:collapse;font-size:.8rem;}
.ins-top-table th{padding:7px 8px;text-align:left;font-size:.72rem;text-transform:uppercase;
  letter-spacing:.04em;color:var(--muted);border-bottom:2px solid var(--border);}
.ins-top-table td{padding:7px 8px;border-bottom:1px solid var(--border);vertical-align:middle;}
.ins-top-table tr:last-child td{border-bottom:none;}
.ins-top-table tr:hover td{background:var(--bg);}
.type-pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.7rem;font-weight:700;}
.type-pill-a{background:#dbeafe;color:#1d4ed8;}
.type-pill-m{background:#fef3c7;color:#92400e;}
.ratio-val{font-weight:700;}
.ratio-val.good{color:var(--good);}
.ratio-val.ok{color:#2855a0;}
.ratio-val.bad{color:var(--bad);}
/* Coverage note */
.ins-coverage{font-size:.73rem;color:var(--muted);background:var(--bg);border-radius:8px;
  padding:10px 14px;margin-top:14px;border-left:3px solid var(--border);line-height:1.6;}
"""

# ─── HTML ─────────────────────────────────────────────────────────────────────
HTML = """
<div id="view-insights" class="hidden">
  <div class="ins-filter-row">
    <span style="font-size:.8rem;font-weight:600;color:var(--muted);margin-right:4px">Afficher :</span>
    <button class="ins-type-btn active" id="ins-btn-all"    onclick="insSetType('all')">Tous</button>
    <button class="ins-type-btn"        id="ins-btn-appart" onclick="insSetType('appart')">🏢 Apparts</button>
    <button class="ins-type-btn"        id="ins-btn-maison" onclick="insSetType('maison')">🏠 Maisons</button>
  </div>

  <!-- KPI row -->
  <div class="ins-kpi-row" id="ins-kpis"></div>

  <!-- Row 1 : AVM distribution + Scatter -->
  <div class="ins-grid-2">
    <div class="ins-card">
      <h3>📊 Distribution ratios AVM</h3>
      <div id="ins-ratio-bars"></div>
    </div>
    <div class="ins-card">
      <h3>🎯 Prix demandé vs AVM</h3>
      <svg id="ins-scatter"></svg>
      <div style="font-size:.7rem;color:var(--muted);margin-top:6px;display:flex;gap:14px">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#3b82f6;margin-right:4px"></span>Appart</span>
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#f59e0b;margin-right:4px"></span>Maison</span>
        <span style="margin-left:auto">Diagonale = prix juste</span>
      </div>
    </div>
  </div>

  <!-- Row 2 : PM2 histogram + Top opportunités -->
  <div class="ins-grid-2">
    <div class="ins-card">
      <h3>📐 Répartition prix / m² bâti</h3>
      <div id="ins-pm2-hist"></div>
    </div>
    <div class="ins-card" style="overflow-x:auto">
      <h3>🏆 Top opportunités (AVM &gt; Prix)</h3>
      <div id="ins-top-table"></div>
    </div>
  </div>

  <!-- Coverage note -->
  <div class="ins-coverage" id="ins-coverage-note"></div>
</div>
"""

# ─── JS ───────────────────────────────────────────────────────────────────────
JS = r"""
// ═══════════════════════════════════════════════════════
// INSIGHTS V2
// ═══════════════════════════════════════════════════════
let _insType = 'all';
function insSetType(t) {
  _insType = t;
  ['all','appart','maison'].forEach(x => {
    document.getElementById('ins-btn-'+x)?.classList.toggle('active', x===t);
  });
  buildInsights();
}

function insMedian(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a,b)=>a-b);
  const m = Math.floor(s.length/2);
  return s.length%2 ? s[m] : (s[m-1]+s[m])/2;
}

function buildInsights() {
  // ── Combiner données ──
  const appts = rows.filter(r => r.price && r.surface && r.location);
  const mais  = MAISONS.filter(m => m.prix && m.surface);

  let data = [];
  if (_insType !== 'maison') {
    appts.forEach(r => data.push({
      type:'appart', label:r.location,
      prix:r.price, surface:r.surface,
      pm2: Math.round(r.price/r.surface),
      avm_pred:r.avm_pred, avm_ratio:r.avm_ratio,
      nb_baisses:r.nb_baisses||0, url:r.url||'',
      yield_pct:r.yield, score:r.score,
      avm_model: r.avm_model,
      chamonix: ['Chamonix','Argentiere'].includes(r.location),
    }));
  }
  if (_insType !== 'appart') {
    mais.forEach(m => data.push({
      type:'maison', label:m.adresse_raw,
      prix:m.prix, surface:m.surface,
      pm2: Math.round(m.prix/m.surface),
      avm_pred:m.avm_pred, avm_ratio:m.avm_ratio,
      nb_baisses:m.nb_baisses||0, url:m.url||'',
      yield_pct:null, score:m.avm_score,
      avm_model:'maison_cham', chamonix:true,
    }));
  }

  const withAvm   = data.filter(d => d.avm_ratio != null);
  const bonnes    = withAvm.filter(d => d.avm_ratio > 1.05).length;
    const baisses   = data.filter(d => d.nb_baisses > 0).length;
  const pxMed     = insMedian(data.map(d=>d.prix).filter(Boolean));
  const sfMed     = insMedian(data.map(d=>d.surface).filter(Boolean));
  const pm2Med    = insMedian(data.map(d=>d.pm2).filter(Boolean));
  const yields    = data.filter(d=>d.yield_pct).map(d=>d.yield_pct);
  const avgYield  = yields.length ? (yields.reduce((a,b)=>a+b)/yields.length).toFixed(1) : null;
  const ratioMed  = insMedian(withAvm.map(d=>d.avm_ratio).filter(Boolean));

  // ── KPIs ──
  const kpiEl = document.getElementById('ins-kpis');
  const fmt = v => v >= 1e6 ? (v/1e6).toFixed(2)+'M€' : Math.round(v).toLocaleString('fr-FR')+'€';
  kpiEl.innerHTML = [
    {v:data.length, l:'Annonces', sub:''},
    {v:pxMed?fmt(pxMed):'-', l:'Prix médian', sub:'', raw:true},
    {v:sfMed?Math.round(sfMed)+'m²':'-', l:'Surface méd.', sub:'', raw:true},
    {v:pm2Med?Math.round(pm2Med).toLocaleString('fr-FR')+'€':'-', l:'PM2 médian', sub:'/m²', raw:true},
    {v:bonnes, l:'AVM > Prix', sub:'bonnes affaires'},
    {v:baisses, l:'Baisses de prix', sub:'actives'},
    ...(avgYield?[{v:avgYield+'%', l:'Rendement moy.', sub:'apparts', raw:true}]:[]),
    ...(ratioMed?[{v:'×'+ratioMed.toFixed(2), l:'Ratio AVM méd.', sub:'AVM/Prix', raw:true}]:[]),
  ].map(k=>`<div class="ins-kpi">
    <div class="ins-kpi-val">${k.raw?k.v:k.v}</div>
    <div class="ins-kpi-lbl">${k.l}</div>
    ${k.sub?`<div class="ins-kpi-sub">${k.sub}</div>`:''}
  </div>`).join('');

  // ── Ratio distribution ──
  const buckets = [
    {lo:-Infinity,hi:0.85, label:'Fortement surcôté', color:'#ef4444'},
    {lo:0.85,     hi:0.95, label:'Surcôté',           color:'#f97316'},
    {lo:0.95,     hi:1.05, label:'Prix marché',        color:'#94a3b8'},
    {lo:1.05,     hi:1.20, label:'Légèrement sous-côté',color:'#86efac'},
    {lo:1.20,     hi:1.50, label:'Bonne affaire',      color:'#22c55e'},
    {lo:1.50,     hi:Infinity,label:'Très bonne affaire',color:'#15803d'},
  ];
  const maxBuck = Math.max(...buckets.map(b=>withAvm.filter(d=>d.avm_ratio>=b.lo&&d.avm_ratio<b.hi).length),1);
  document.getElementById('ins-ratio-bars').innerHTML = buckets.map(b=>{
    const n = withAvm.filter(d => d.avm_ratio >= b.lo && d.avm_ratio < b.hi).length;
    const w = n ? Math.max(4, Math.round(n/maxBuck*100)) : 0;
    return `<div class="ratio-bar-row">
      <div class="ratio-bar-label">${b.label}</div>
      <div class="ratio-bar-track">
        <div class="ratio-bar-fill" style="width:${w}%;background:${b.color}">
          ${n>0?`<span>${n}</span>`:''}
        </div>
      </div>
      <div class="ratio-bar-count">${n}</div>
    </div>`;
  }).join('') + `<div style="font-size:.72rem;color:var(--muted);margin-top:8px">${withAvm.length} annonces avec AVM sur ${data.length}</div>`;

  // ── Scatter SVG ──
  const svg = document.getElementById('ins-scatter');
  const W = svg.parentElement.clientWidth - 40 || 320;
  const H = 260;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('width', W);
  svg.setAttribute('height', H);
  const pad = {l:50,r:20,t:12,b:36};
  const pts = withAvm.filter(d=>d.prix&&d.avm_pred);
  if (!pts.length) { svg.innerHTML='<text x="50%" y="50%" text-anchor="middle" fill="#94a3b8">Aucune donnée</text>'; return; }
  const allVals = pts.flatMap(d=>[d.prix,d.avm_pred]);
  const vMin = Math.min(...allVals)*0.9, vMax = Math.max(...allVals)*1.05;
  const sc = v => pad.l + (v-vMin)/(vMax-vMin)*(W-pad.l-pad.r);
  const sy = v => H-pad.b - (v-vMin)/(vMax-vMin)*(H-pad.t-pad.b);
  // Grid lines
  let svgContent = '';
  const ticks = 4;
  for (let i=0;i<=ticks;i++) {
    const v = vMin + i*(vMax-vMin)/ticks;
    const x = sc(v), y = sy(v);
    svgContent += `<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${H-pad.b}" stroke="#e2e8f0" stroke-width="1"/>`;
    svgContent += `<line x1="${pad.l}" y1="${y}" x2="${W-pad.r}" y2="${y}" stroke="#e2e8f0" stroke-width="1"/>`;
    const lbl = v>=1e6?(v/1e6).toFixed(1)+'M':(v/1e3).toFixed(0)+'k';
    svgContent += `<text x="${x}" y="${H-pad.b+14}" text-anchor="middle" font-size="10" fill="#94a3b8">${lbl}</text>`;
    svgContent += `<text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="10" fill="#94a3b8">${lbl}</text>`;
  }
  // Diagonal (fair value)
  svgContent += `<line x1="${sc(vMin)}" y1="${sy(vMin)}" x2="${sc(vMax)}" y2="${sy(vMax)}" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="5,4"/>`;
  // +20% / -20% bands
  svgContent += `<line x1="${sc(vMin)}" y1="${sy(vMin*1.2)}" x2="${sc(vMax/1.2)}" y2="${sy(vMax)}" stroke="#86efac" stroke-width="1" stroke-dasharray="3,4" opacity=".6"/>`;
  svgContent += `<line x1="${sc(vMin*1.2)}" y1="${sy(vMin)}" x2="${sc(vMax)}" y2="${sy(vMax/1.2)}" stroke="#fca5a5" stroke-width="1" stroke-dasharray="3,4" opacity=".6"/>`;
  // Points
  pts.forEach(d => {
    const x = sc(d.prix), y = sy(d.avm_pred);
    const r = d.type==='maison' ? Math.max(4,Math.min(9,d.surface/30)) : Math.max(3,Math.min(7,d.surface/15));
    const fill = d.type==='appart' ? '#3b82f6' : '#f59e0b';
    const lbl = (d.avm_ratio>=1.1?'↑':'') + '×'+d.avm_ratio.toFixed(2);
    svgContent += `<circle cx="${x}" cy="${y}" r="${r}" fill="${fill}" opacity=".75" stroke="#fff" stroke-width="1">
      <title>${d.label} · ${d.type} · Prix: ${(d.prix/1e3).toFixed(0)}k€ · AVM: ${(d.avm_pred/1e3).toFixed(0)}k€ · ×${d.avm_ratio.toFixed(2)}</title>
    </circle>`;
  });
  // Axes labels
  svgContent += `<text x="${W/2}" y="${H}" text-anchor="middle" font-size="11" fill="#64748b">Prix demandé →</text>`;
  svgContent += `<text x="12" y="${H/2}" text-anchor="middle" font-size="11" fill="#64748b" transform="rotate(-90,12,${H/2})">AVM →</text>`;
  svg.innerHTML = svgContent;

  // ── PM2 histogram ──
  const pm2Buckets = [
    {lo:0,    hi:5000,  label:'< 5k'},
    {lo:5000, hi:7000,  label:'5-7k'},
    {lo:7000, hi:9000,  label:'7-9k'},
    {lo:9000, hi:11000, label:'9-11k'},
    {lo:11000,hi:14000, label:'11-14k'},
    {lo:14000,hi:18000, label:'14-18k'},
    {lo:18000,hi:Infinity,label:'18k+'},
  ];
  const apptPm2 = data.filter(d=>d.type==='appart'&&d.pm2);
  const maisPm2 = data.filter(d=>d.type==='maison'&&d.pm2);
  const maxPm2  = Math.max(...pm2Buckets.map(b=>{
    const na=apptPm2.filter(d=>d.pm2>=b.lo&&d.pm2<b.hi).length;
    const nm=maisPm2.filter(d=>d.pm2>=b.lo&&d.pm2<b.hi).length;
    return Math.max(na,nm);
  }),1);
  const pm2El = document.getElementById('ins-pm2-hist');
  pm2El.innerHTML = pm2Buckets.map(b=>{
    const na=apptPm2.filter(d=>d.pm2>=b.lo&&d.pm2<b.hi).length;
    const nm=maisPm2.filter(d=>d.pm2>=b.lo&&d.pm2<b.hi).length;
    if(!na&&!nm) return '';
    const wa=Math.max(na?4:0,Math.round(na/maxPm2*100));
    const wm=Math.max(nm?4:0,Math.round(nm/maxPm2*100));
    return `<div class="pm2-hist-row">
      <div class="pm2-hist-lbl">${b.label}</div>
      <div class="pm2-hist-bars">
        ${na?`<div class="pm2-hist-bar" style="width:${wa}%;background:#3b82f6;opacity:.8" title="${na} appart(s)"></div>`:''}
        ${nm?`<div class="pm2-hist-bar" style="width:${wm}%;background:#f59e0b;opacity:.8" title="${nm} maison(s)"></div>`:''}
      </div>
      <div style="font-size:.7rem;color:var(--muted);width:50px;flex-shrink:0">
        ${na?`<span style="color:#3b82f6">${na}a</span> `:''}${nm?`<span style="color:#f59e0b">${nm}m</span>`:''}
      </div>
    </div>`;
  }).join('') + `<div style="font-size:.7rem;color:var(--muted);margin-top:8px;display:flex;gap:12px">
    <span><span style="display:inline-block;width:10px;height:6px;background:#3b82f6;border-radius:2px;margin-right:4px"></span>Appart</span>
    <span><span style="display:inline-block;width:10px;height:6px;background:#f59e0b;border-radius:2px;margin-right:4px"></span>Maison (bâti/m²)</span>
  </div>`;

  // ── Top opportunités ──
  const top = [...withAvm]
    .filter(d=>d.avm_ratio>1.0)
    .sort((a,b)=>b.avm_ratio-a.avm_ratio)
    .slice(0,8);
  const ratioClass = r => r>=1.3?'good':r>=1.05?'ok':'bad';
  document.getElementById('ins-top-table').innerHTML = top.length ? `
    <table class="ins-top-table">
      <thead><tr><th>Type</th><th>Bien</th><th>Surface</th><th>Prix</th><th>AVM</th><th>Ratio</th></tr></thead>
      <tbody>
      ${top.map(d=>`<tr>
        <td><span class="type-pill ${d.type==='appart'?'type-pill-a':'type-pill-m'}">${d.type==='appart'?'APT':'MNS'}</span></td>
        <td>${d.url?`<a href="${d.url}" target="_blank" style="color:var(--accent)">${(d.label||'').substring(0,28)}…</a>`:(d.label||'—').substring(0,30)}</td>
        <td>${Math.round(d.surface)}m²</td>
        <td>${(d.prix/1e6).toFixed(3)}M</td>
        <td>${d.avm_pred?(d.avm_pred/1e6).toFixed(3)+'M':'—'}</td>
        <td><span class="ratio-val ${ratioClass(d.avm_ratio)}">×${d.avm_ratio.toFixed(2)}</span></td>
      </tr>`).join('')}
      </tbody>
    </table>` : '<div style="color:var(--muted);font-size:.85rem;padding:12px 0">Aucune opportunité AVM > Prix dans la sélection</div>';

  // ── Coverage note ──
  const nChamApt = data.filter(d=>d.type==='appart'&&d.chamonix&&d.avm_pred).length;
  const nVallApt = data.filter(d=>d.type==='appart'&&!d.chamonix&&d.avm_pred).length;
  const nMai     = data.filter(d=>d.type==='maison'&&d.avm_pred).length;
  document.getElementById('ins-coverage-note').innerHTML =
    `<strong>Couverture AVM</strong> — `+
    (nChamApt?`<strong>${nChamApt} appart${nChamApt>1?'s':''} Chamonix/Argentière</strong> : modèle XGBoost calibré, MAPE <strong>8.8%</strong>, P80 ±14%. `:'')+
    (nVallApt?`<strong>${nVallApt} appart${nVallApt>1?'s':''} vallée</strong> : modèle multi-communes, précision ~15%. `:'')+
    (nMai?`<strong>${nMai} maison${nMai>1?'s':''} Chamonix</strong> : modèle XGBoost calibré, MAPE <strong>15.3%</strong>, P80 ±25%. `:'')+
    `Les communes hors Chamonix n'ont pas de modèle maison dédié.`;
}
"""

# ─── Injection ────────────────────────────────────────────────────────────────

# 1. Remplace div insights (vide → contenu)
html = html.replace(
    '<div id="view-insights" class="hidden"></div>',
    HTML.strip()
)

# 2. CSS
html = html.replace('</style>', CSS + '\n</style>', 1)

# 3. JS — remplace l'ancienne fonction buildInsights si elle existe, sinon ajoute
old_fn = re.search(r'function buildInsights\(\)\s*\{.*?\n\}', html, re.DOTALL)
if old_fn:
    html = html[:old_fn.start()] + JS.strip() + html[old_fn.end():]
    print("buildInsights remplacee")
else:
    # Ajouter avant </script>
    html = html.replace('</script>', JS.strip() + '\n</script>', 1)
    print("buildInsights ajoutee")

DASH.write_text(html, encoding="utf-8")
size_kb = len(html) // 1024
print(f"dashboard.html mis a jour ({size_kb} KB)")
print("Insights v2 injecte : filter + KPIs + ratio bars + scatter + PM2 hist + top table")
