"""
_inject_insights_v3.py
=======================
Insights tab v3 – remplacement complet de buildInsights() :
  - Filter Tous / Apparts / Maisons + toggle AVM seulement
  - KPI row (+ fraîcheur <7j)
  - PM2 par commune (bar horizontal, comparatif)
  - AVM distribution + Scatter (Chamonix/Argentière UNIQUEMENT)
  - Top 8 opportunités
  - Tableau comparatif par commune
  - Heatmap Leaflet (lazy CDN, jitter spiral, couleurs PM2/Ratio/Score)
  - Coverage note précise
"""
import re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent
DASH = BASE / "dashboard.html"
html = DASH.read_text(encoding="utf-8")

# ── CSS (incremental) ─────────────────────────────────────────────────────────
CSS = """
/* ── Insights v3 additions ── */
.ins-full{grid-column:1/-1;}
.ins-section-hdr{font-size:.75rem;font-weight:800;color:var(--muted);text-transform:uppercase;
  letter-spacing:.06em;margin:18px 0 10px;display:flex;align-items:center;gap:8px;}
.ins-section-hdr::after{content:'';flex:1;height:1px;background:var(--border);}
/* KPI badges */
.ins-kpi-badge{font-size:.65rem;padding:1px 6px;border-radius:8px;font-weight:700;margin-top:4px;display:inline-block;}
.ins-kpi-badge.fresh{background:#dcfce7;color:#166534;}
.ins-kpi-badge.stale{background:#fef9c3;color:#713f12;}
/* PM2 commune bars */
.pm2-com-row{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:.78rem;}
.pm2-com-label{width:100px;flex-shrink:0;color:var(--text);font-weight:600;text-overflow:ellipsis;overflow:hidden;white-space:nowrap;}
.pm2-com-bars{flex:1;display:flex;flex-direction:column;gap:2px;}
.pm2-com-bar{border-radius:3px;height:11px;min-width:3px;position:relative;transition:width .3s;}
.pm2-com-val{font-size:.7rem;color:var(--muted);width:70px;flex-shrink:0;text-align:right;}
/* Commune table */
.ins-com-table{width:100%;border-collapse:collapse;font-size:.78rem;}
.ins-com-table th{padding:8px 10px;text-align:left;font-size:.71rem;text-transform:uppercase;
  letter-spacing:.04em;color:var(--muted);border-bottom:2px solid var(--border);white-space:nowrap;}
.ins-com-table td{padding:7px 10px;border-bottom:1px solid var(--border);vertical-align:middle;}
.ins-com-table tr:last-child td{border-bottom:none;}
.ins-com-table tr:hover td{background:var(--bg);}
.ins-com-badge{font-size:.7rem;padding:2px 7px;border-radius:8px;font-weight:700;}
.ins-com-badge.cham{background:#dbeafe;color:#1d4ed8;}
.ins-com-badge.vallee{background:#f1f5f9;color:#475569;}
.ins-avm-qualified{font-size:.68rem;color:#1d4ed8;font-weight:600;}
.ins-avm-na{font-size:.68rem;color:var(--muted);}
/* Leaflet map */
#ins-map{height:430px;border-radius:10px;z-index:1;border:1px solid var(--border);}
.ins-map-controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;align-items:center;}
.ins-map-chip{padding:5px 13px;border:1.5px solid var(--border);border-radius:16px;
  background:var(--card);cursor:pointer;font-size:.75rem;font-weight:600;
  color:var(--muted);transition:all .12s;}
.ins-map-chip:hover{border-color:var(--accent);}
.ins-map-chip.active{border-color:var(--accent);background:var(--accent);color:#fff;}
.ins-map-sep{width:1px;height:20px;background:var(--border);flex-shrink:0;}
.ins-map-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:.71rem;color:var(--muted);}
.ins-map-legend-item{display:flex;align-items:center;gap:5px;}
.ins-map-legend-dot{width:12px;height:12px;border-radius:50%;}
/* AVM constraint banner */
.ins-avm-banner{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;
  padding:8px 14px;margin-bottom:12px;font-size:.76rem;color:#1e40af;line-height:1.5;}
"""

# ── JS buildInsights v3 ───────────────────────────────────────────────────────
JS = r"""
// ═══════════════════════════════════════════════════════
// INSIGHTS V3 — Maisons + Apparts + Heatmap Leaflet
// ═══════════════════════════════════════════════════════
let _insType   = 'all';
let _insMapType= 'all';
let _insMetric = 'pm2';
let _insLeaflet= null; // Leaflet map instance

function insSetType(t) {
  _insType = t;
  ['all','appart','maison'].forEach(x =>
    document.getElementById('ins-btn-'+x)?.classList.toggle('active', x===t));
  buildInsights();
}

function insSetMapType(t) {
  _insMapType = t;
  ['all','appart','maison'].forEach(x =>
    document.getElementById('ins-map-type-'+x)?.classList.toggle('active', x===t));
  renderInsMap();
}

function insSetMetric(m) {
  _insMetric = m;
  ['pm2','ratio','score'].forEach(x =>
    document.getElementById('ins-met-'+x)?.classList.toggle('active', x===m));
  renderInsMap();
}

function insMed(arr) {
  if (!arr.length) return null;
  const s=[...arr].sort((a,b)=>a-b); const m=Math.floor(s.length/2);
  return s.length%2?s[m]:(s[m-1]+s[m])/2;
}
function insFmt(v){return v>=1e6?(v/1e6).toFixed(2)+'M€':Math.round(v).toLocaleString('fr-FR')+'€';}
function insAge(d){if(!d)return null;const now=new Date(),t=new Date(d);return Math.floor((now-t)/864e5);}

function buildInsights() {
  const c = document.getElementById('view-insights');
  if (!c) return;

  // ── Construire données unifiées ──────────────────────────────────────────
  const CHAM_LOCS = ['Chamonix','Argentiere'];
  const allAppts = rows.filter(r=>r.price&&r.surface);
  const allMais  = MAISONS.filter(m=>m.prix&&m.surface);

  let data = [];
  if (_insType !== 'maison') {
    allAppts.forEach((r,i) => data.push({
      type:'appart', label:r.location||'?',
      prix:r.price, surface:r.surface, rooms:r.rooms,
      pm2:r.price/r.surface, score:+(r.score||0),
      avm_pred:r.avm_pred||null, avm_ratio:r.avm_ratio||null,
      avm_qualified: CHAM_LOCS.includes(r.location) && !!r.avm_pred,
      avm_model:r.avm_model||null,
      nb_baisses:r.nb_baisses||0, url:r.url||'',
      first_seen:r.first_seen||null, location:r.location||'?',
      section:null, _idx:i
    }));
  }
  if (_insType !== 'appart') {
    allMais.forEach((m,i) => data.push({
      type:'maison', label:m.adresse_raw||'Chamonix',
      prix:m.prix, surface:m.surface, rooms:m.pieces,
      pm2:m.prix/m.surface, score:+(m.avm_score||0),
      avm_pred:m.avm_pred||null, avm_ratio:m.avm_ratio||null,
      avm_qualified:!!m.avm_pred,
      avm_model:'maison_cham',
      nb_baisses:m.nb_baisses||0, url:m.url||'',
      first_seen:m.first_seen||null, location:'Chamonix',
      section:m.section||'G', _idx:i
    }));
  }

  const qualAVM = data.filter(d=>d.avm_qualified);
  const bonnes  = qualAVM.filter(d=>d.avm_ratio>=1.05).length;
  const baisses = data.filter(d=>d.nb_baisses>0).length;
  const fresh   = data.filter(d=>insAge(d.first_seen)!=null&&insAge(d.first_seen)<=7).length;
  const pxMed   = insMed(data.map(d=>d.prix).filter(Boolean));
  const sfMed   = insMed(data.map(d=>d.surface).filter(Boolean));
  const pm2Med  = insMed(data.map(d=>d.pm2).filter(Boolean));
  const ratioMed= insMed(qualAVM.map(d=>d.avm_ratio).filter(Boolean));

  // ── BUILD HTML ────────────────────────────────────────────────────────────
  let html = `
  <div class="ins-filter-row">
    <span style="font-size:.8rem;font-weight:600;color:var(--muted);margin-right:4px">Marché :</span>
    <button class="ins-type-btn ${_insType==='all'?'active':''}"    id="ins-btn-all"    onclick="insSetType('all')">Tous</button>
    <button class="ins-type-btn ${_insType==='appart'?'active':''}" id="ins-btn-appart" onclick="insSetType('appart')">🏢 Apparts</button>
    <button class="ins-type-btn ${_insType==='maison'?'active':''}" id="ins-btn-maison" onclick="insSetType('maison')">🏠 Maisons</button>
  </div>`;

  // ── KPIs ──────────────────────────────────────────────────────────────────
  const kpis = [
    {v:data.length, l:'Annonces', sub:'actives'},
    {v:pxMed?insFmt(pxMed):'—', l:'Prix médian', raw:true},
    {v:pm2Med?Math.round(pm2Med).toLocaleString('fr-FR')+'€':'—', l:'PM2 médian', sub:'/m² bâti', raw:true},
    {v:sfMed?Math.round(sfMed)+'m²':'—', l:'Surface méd.', raw:true},
    {v:`${bonnes}<span class="ins-kpi-badge fresh">AVM>Prix</span>`, l:'Bonnes affaires', raw:true},
    {v:baisses, l:'Baisses de prix', sub:'actives'},
    {v:fresh>0?`${fresh}<span class="ins-kpi-badge fresh">&lt;7j</span>`:`0`, l:'Nouvelles annonces', raw:true},
    ...(ratioMed?[{v:'×'+ratioMed.toFixed(2), l:'Ratio AVM méd.', sub:'Cham/Arg', raw:true}]:[]),
  ];
  html += `<div class="ins-kpi-row">${kpis.map(k=>`
    <div class="ins-kpi">
      <div class="ins-kpi-val">${k.raw?k.v:k.v}</div>
      <div class="ins-kpi-lbl">${k.l}</div>
      ${k.sub?`<div class="ins-kpi-sub">${k.sub}</div>`:''}
    </div>`).join('')}</div>`;

  // ── Section 1 : Analyse du marché ─────────────────────────────────────────
  html += `<div class="ins-section-hdr">📊 Analyse du marché</div>
  <div class="ins-grid-2">`;

  // PM2 par commune (bar horizontal)
  const communes = [...new Set(data.map(d=>d.location))].sort();
  const maxPM2   = Math.max(...communes.flatMap(com=>{
    const dA=data.filter(d=>d.location===com&&d.type==='appart');
    const dM=data.filter(d=>d.location===com&&d.type==='maison');
    return [insMed(dA.map(d=>d.pm2))||0, insMed(dM.map(d=>d.pm2))||0];
  }),1);
  const comBars = communes.map(com=>{
    const dA=data.filter(d=>d.location===com&&d.type==='appart');
    const dM=data.filter(d=>d.location===com&&d.type==='maison');
    const pm2A=insMed(dA.map(d=>d.pm2));
    const pm2M=insMed(dM.map(d=>d.pm2));
    if(!pm2A&&!pm2M) return '';
    const wA=pm2A?Math.max(4,Math.round(pm2A/maxPM2*100)):0;
    const wM=pm2M?Math.max(4,Math.round(pm2M/maxPM2*100)):0;
    return `<div class="pm2-com-row">
      <div class="pm2-com-label" title="${com}">${com}</div>
      <div class="pm2-com-bars">
        ${pm2A?`<div class="pm2-com-bar" style="width:${wA}%;background:#3b82f6;opacity:.85" title="Apparts: ${Math.round(pm2A).toLocaleString('fr-FR')} €/m²"></div>`:''}
        ${pm2M?`<div class="pm2-com-bar" style="width:${wM}%;background:#f59e0b;opacity:.85" title="Maisons: ${Math.round(pm2M).toLocaleString('fr-FR')} €/m²"></div>`:''}
      </div>
      <div class="pm2-com-val">${pm2A?Math.round(pm2A/1000).toFixed(0)+'k':''} ${pm2M?'/ '+Math.round(pm2M/1000).toFixed(0)+'k':''}</div>
    </div>`;
  }).join('');
  html += `<div class="ins-card">
    <h3>📐 Prix / m² par commune</h3>
    ${comBars}
    <div style="display:flex;gap:14px;margin-top:8px;font-size:.7rem;color:var(--muted)">
      <span><span style="display:inline-block;width:10px;height:6px;background:#3b82f6;border-radius:2px;margin-right:4px"></span>Appart</span>
      <span><span style="display:inline-block;width:10px;height:6px;background:#f59e0b;border-radius:2px;margin-right:4px"></span>Maison (bâti)</span>
    </div>
  </div>`;

  // Top 8 opportunités (AVM qualifié uniquement)
  const topOpps = [...qualAVM].filter(d=>d.avm_ratio>1.0)
    .sort((a,b)=>b.avm_ratio-a.avm_ratio).slice(0,8);
  const rtClass = r => r>=1.3?'good':r>=1.05?'ok':'bad';
  html += `<div class="ins-card" style="overflow-x:auto">
    <h3>🏆 Top opportunités <span style="font-size:.7rem;font-weight:400;color:var(--muted)">(AVM > Prix, Chamonix)</span></h3>
    ${topOpps.length?`<table class="ins-top-table">
      <thead><tr><th></th><th>Bien</th><th>Surf.</th><th>Prix</th><th>AVM</th><th>Ratio</th></tr></thead>
      <tbody>${topOpps.map(d=>`<tr>
        <td><span class="type-pill ${d.type==='appart'?'type-pill-a':'type-pill-m'}">${d.type==='appart'?'APT':'MNS'}</span></td>
        <td>${d.url?`<a href="${d.url}" target="_blank" style="color:var(--accent)">${(d.label||'').substring(0,22)}…</a>`:(d.label||'—').substring(0,24)}</td>
        <td>${Math.round(d.surface)}m²</td>
        <td>${(d.prix/1e6).toFixed(2)}M</td>
        <td>${(d.avm_pred/1e6).toFixed(2)}M</td>
        <td><span class="ratio-val ${rtClass(d.avm_ratio)}">×${d.avm_ratio.toFixed(2)}</span></td>
      </tr>`).join('')}</tbody>
    </table>`:`<div style="color:var(--muted);font-size:.85rem;padding:12px 0">Aucune opportunité AVM>Prix</div>`}
  </div>`;
  html += `</div>`; // end ins-grid-2

  // ── Section 2 : AVM Chamonix/Argentière ───────────────────────────────────
  if (qualAVM.length) {
    html += `<div class="ins-section-hdr">🎯 AVM — Chamonix &amp; Argentière uniquement</div>
    <div class="ins-avm-banner">
      ℹ️ Les ratios AVM ci-dessous n'incluent que les annonces avec modèle précis :
      <strong>${qualAVM.filter(d=>d.type==='appart').length} apparts Chamonix/Argentière</strong> (MAPE 8.8%, P80 ±14%)
      + <strong>${qualAVM.filter(d=>d.type==='maison').length} maisons Chamonix</strong> (MAPE 15.3%, P80 ±25%).
    </div>
    <div class="ins-grid-2">`;

    // Distribution ratios AVM
    const buckets = [
      {lo:-Infinity,hi:0.85,label:'Fortement surcôté',color:'#ef4444'},
      {lo:0.85,hi:0.95,label:'Surcôté',color:'#f97316'},
      {lo:0.95,hi:1.05,label:'Prix marché',color:'#94a3b8'},
      {lo:1.05,hi:1.20,label:'Légèrement sous-côté',color:'#86efac'},
      {lo:1.20,hi:1.50,label:'Bonne affaire',color:'#22c55e'},
      {lo:1.50,hi:Infinity,label:'Très bonne affaire',color:'#15803d'},
    ];
    const maxB = Math.max(...buckets.map(b=>qualAVM.filter(d=>d.avm_ratio>=b.lo&&d.avm_ratio<b.hi).length),1);
    const barsHtml = buckets.map(b=>{
      const n=qualAVM.filter(d=>d.avm_ratio>=b.lo&&d.avm_ratio<b.hi).length;
      const w=n?Math.max(4,Math.round(n/maxB*100)):0;
      return `<div class="ratio-bar-row">
        <div class="ratio-bar-label">${b.label}</div>
        <div class="ratio-bar-track">
          <div class="ratio-bar-fill" style="width:${w}%;background:${b.color}">${n>0?`<span>${n}</span>`:''}</div>
        </div>
        <div class="ratio-bar-count">${n}</div>
      </div>`;
    }).join('');
    html += `<div class="ins-card">
      <h3>📊 Distribution ratios AVM</h3>
      ${barsHtml}
      <div style="font-size:.72rem;color:var(--muted);margin-top:8px">${qualAVM.length} annonces AVM qualifiées sur ${data.length}</div>
    </div>`;

    // Scatter SVG
    const pts = qualAVM.filter(d=>d.prix&&d.avm_pred);
    const W=460,H=260,pad={l:52,r:18,t:12,b:36};
    const allV=pts.flatMap(d=>[d.prix,d.avm_pred]);
    const vMin=Math.min(...allV)*.88,vMax=Math.max(...allV)*1.08;
    const sc=v=>pad.l+(v-vMin)/(vMax-vMin)*(W-pad.l-pad.r);
    const sy=v=>H-pad.b-(v-vMin)/(vMax-vMin)*(H-pad.t-pad.b);
    let svgC='';
    for(let i=0;i<=4;i++){
      const v=vMin+i*(vMax-vMin)/4;
      const x=sc(v),y=sy(v);
      svgC+=`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${H-pad.b}" stroke="#e2e8f0" stroke-width="1"/>
              <line x1="${pad.l}" y1="${y}" x2="${W-pad.r}" y2="${y}" stroke="#e2e8f0" stroke-width="1"/>`;
      const lbl=v>=1e6?(v/1e6).toFixed(1)+'M':(v/1e3).toFixed(0)+'k';
      svgC+=`<text x="${x}" y="${H-pad.b+13}" text-anchor="middle" font-size="10" fill="#94a3b8">${lbl}</text>
             <text x="${pad.l-4}" y="${y+4}" text-anchor="end" font-size="10" fill="#94a3b8">${lbl}</text>`;
    }
    svgC+=`<line x1="${sc(vMin)}" y1="${sy(vMin)}" x2="${sc(vMax)}" y2="${sy(vMax)}" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="5,4"/>`;
    svgC+=`<line x1="${sc(vMin)}" y1="${sy(vMin*1.2)}" x2="${sc(vMax/1.2)}" y2="${sy(vMax)}" stroke="#86efac" stroke-width="1" stroke-dasharray="3,4" opacity=".6"/>`;
    svgC+=`<line x1="${sc(vMin*1.2)}" y1="${sy(vMin)}" x2="${sc(vMax)}" y2="${sy(vMax/1.2)}" stroke="#fca5a5" stroke-width="1" stroke-dasharray="3,4" opacity=".6"/>`;
    pts.forEach(d=>{
      const r=d.type==='maison'?Math.max(4,Math.min(8,d.surface/28)):Math.max(3,Math.min(6,d.surface/14));
      const fill=d.type==='appart'?'#3b82f6':'#f59e0b';
      svgC+=`<circle cx="${sc(d.prix)}" cy="${sy(d.avm_pred)}" r="${r}" fill="${fill}" opacity=".78" stroke="#fff" stroke-width="1">
        <title>${d.label} · ${d.type} · Prix: ${(d.prix/1e3).toFixed(0)}k€ · AVM: ${(d.avm_pred/1e3).toFixed(0)}k€ · ×${d.avm_ratio.toFixed(2)}</title>
      </circle>`;
    });
    svgC+=`<text x="${W/2}" y="${H-1}" text-anchor="middle" font-size="11" fill="#64748b">Prix demandé →</text>
           <text x="10" y="${H/2}" text-anchor="middle" font-size="11" fill="#64748b" transform="rotate(-90,10,${H/2})">AVM →</text>`;
    html += `<div class="ins-card">
      <h3>🎯 Prix demandé vs AVM</h3>
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" style="max-height:${H}px">${svgC}</svg>
      <div style="font-size:.7rem;color:var(--muted);margin-top:5px;display:flex;gap:14px;flex-wrap:wrap">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#3b82f6;margin-right:4px"></span>Appart Cham.</span>
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#f59e0b;margin-right:4px"></span>Maison</span>
        <span style="margin-left:auto">— diagonale = juste prix</span>
      </div>
    </div>`;
    html += `</div>`; // end ins-grid-2
  }

  // ── Section 3 : Tableau comparatif par commune ────────────────────────────
  html += `<div class="ins-section-hdr">📋 Comparatif par commune</div>
  <div class="ins-card ins-full" style="overflow-x:auto">
    <table class="ins-com-table">
      <thead><tr>
        <th>Commune</th><th>N appts</th><th>Prix méd.</th><th>PM2</th>
        <th>N maisons</th><th>Prix méd.</th><th>PM2</th>
        <th>Ratio AVM</th><th>Modèle</th>
      </tr></thead>
      <tbody>`;
  const allComs = [...new Set([...allAppts.map(r=>r.location||'?'),...allMais.map(()=>'Chamonix')])].sort();
  allComs.forEach(com=>{
    const apts = data.filter(d=>d.location===com&&d.type==='appart');
    const mais = data.filter(d=>d.location===com&&d.type==='maison');
    const isCham = com==='Chamonix'||com==='Argentiere';
    const apmMed = insMed(apts.map(d=>d.pm2).filter(Boolean));
    const maiPmMed= insMed(mais.map(d=>d.pm2).filter(Boolean));
    const aptPxMed= insMed(apts.map(d=>d.prix).filter(Boolean));
    const maiPxMed= insMed(mais.map(d=>d.prix).filter(Boolean));
    const qAvm = [...apts,...mais].filter(d=>d.avm_qualified);
    const avmR = insMed(qAvm.map(d=>d.avm_ratio).filter(Boolean));
    const ratioHtml = avmR
      ? `<span class="ratio-val ${avmR>=1.1?'good':avmR>=0.95?'ok':'bad'}">×${avmR.toFixed(2)}</span>`
      : `<span class="ins-avm-na">—</span>`;
    const modelBadge = isCham
      ? `<span class="ins-com-badge cham">Cham 8.8%</span>`
      : `<span class="ins-com-badge vallee">Vallée ~15%</span>`;
    html += `<tr>
      <td><strong>${com}</strong></td>
      <td>${apts.length||'—'}</td>
      <td>${aptPxMed?insFmt(aptPxMed):'—'}</td>
      <td>${apmMed?Math.round(apmMed/1000).toFixed(0)+'k €/m²':'—'}</td>
      <td>${mais.length||'—'}</td>
      <td>${maiPxMed?insFmt(maiPxMed):'—'}</td>
      <td>${maiPmMed?Math.round(maiPmMed/1000).toFixed(0)+'k €/m²':'—'}</td>
      <td>${ratioHtml}</td>
      <td>${isCham?modelBadge:mais.length?'<span class="ins-avm-na">—</span>':modelBadge}</td>
    </tr>`;
  });
  html += `</tbody></table></div>`;

  // ── Section 4 : Heatmap ───────────────────────────────────────────────────
  html += `<div class="ins-section-hdr">🗺️ Carte du marché</div>
  <div class="ins-card ins-full">
    <div class="ins-map-controls">
      <span style="font-size:.75rem;font-weight:700;color:var(--muted)">Type :</span>
      <button class="ins-map-chip ${_insMapType==='all'?'active':''}"    id="ins-map-type-all"    onclick="insSetMapType('all')">Tous</button>
      <button class="ins-map-chip ${_insMapType==='appart'?'active':''}" id="ins-map-type-appart" onclick="insSetMapType('appart')">🏢 Apparts</button>
      <button class="ins-map-chip ${_insMapType==='maison'?'active':''}" id="ins-map-type-maison" onclick="insSetMapType('maison')">🏠 Maisons</button>
      <div class="ins-map-sep"></div>
      <span style="font-size:.75rem;font-weight:700;color:var(--muted)">Couleur :</span>
      <button class="ins-map-chip ${_insMetric==='pm2'?'active':''}"   id="ins-met-pm2"   onclick="insSetMetric('pm2')">€/m²</button>
      <button class="ins-map-chip ${_insMetric==='ratio'?'active':''}" id="ins-met-ratio" onclick="insSetMetric('ratio')">Ratio AVM</button>
      <button class="ins-map-chip ${_insMetric==='score'?'active':''}" id="ins-met-score" onclick="insSetMetric('score')">Score</button>
    </div>
    <div id="ins-map"></div>
    <div class="ins-map-legend" id="ins-map-legend"></div>
  </div>`;

  // ── Coverage note ─────────────────────────────────────────────────────────
  const nQA=qualAVM.filter(d=>d.type==='appart').length;
  const nQM=qualAVM.filter(d=>d.type==='maison').length;
  const nV =data.filter(d=>d.type==='appart'&&!d.avm_qualified&&d.avm_pred).length;
  html += `<div class="ins-coverage">
    <strong>Couverture AVM</strong> —
    ${nQA?`<strong>${nQA} appart${nQA>1?'s':''} Chamonix/Argentière</strong> : XGBoost calibré MAPE <strong>8.8%</strong>, P80 ±14%. `:''}
    ${nQM?`<strong>${nQM} maison${nQM>1?'s':''} Chamonix</strong> : XGBoost MAPE <strong>15.3%</strong>, P80 ±25%. `:''}
    ${nV?`<strong>${nV} appart${nV>1?'s':''} vallée</strong> : modèle multi-communes, indicatif ~15%, <em>non inclus dans l'analyse AVM</em>. `:''}
    Les communes hors Chamonix n'ont pas de modèle maison dédié.
  </div>`;

  // ── Inject HTML ───────────────────────────────────────────────────────────
  c.innerHTML = html;

  // ── Lancer la carte ───────────────────────────────────────────────────────
  window._insData = data;
  loadInsLeaflet();
}

// ─── Leaflet map ─────────────────────────────────────────────────────────────
const INS_COM_GEO = {
  'Chamonix':      [45.923, 6.869],
  'Argentiere':    [45.978, 6.920],
  'Les Houches':   [45.894, 6.797],
  'Saint-Gervais': [45.889, 6.709],
  'Sallanches':    [45.937, 6.634],
  'Passy':         [45.927, 6.707],
  'Servoz':        [45.931, 6.763],
};
const INS_SEC_GEO = {
  'A': [46.015, 6.926], 'B': [45.978, 6.921], 'C': [45.948, 6.900],
  'D': [45.930, 6.883], 'E': [45.890, 6.849], 'G': [45.923, 6.870],
  'H': [45.907, 6.830], 'I': [45.915, 6.855], 'J': [45.920, 6.840],
};

function getInsCoords(d, idxInGroup, groupSize) {
  let baseLat, baseLon;
  if (d.type === 'maison') {
    const geo = INS_SEC_GEO[d.section] || INS_COM_GEO['Chamonix'];
    baseLat = geo[0]; baseLon = geo[1];
  } else {
    const geo = INS_COM_GEO[d.location] || INS_COM_GEO['Chamonix'];
    baseLat = geo[0]; baseLon = geo[1];
  }
  if (groupSize <= 1) return [baseLat, baseLon];
  // Sunflower spiral jitter (deterministic by index)
  const r = Math.sqrt((idxInGroup + 0.5) / Math.max(groupSize, 1)) * 0.009;
  const theta = idxInGroup * 2.3999632;
  return [baseLat + Math.cos(theta) * r, baseLon + Math.sin(theta) * r];
}

function insColorPM2(pm2) {
  // Blue(low)→Green(mid)→Red(high), scale 5000–18000
  const t = Math.max(0, Math.min(1, (pm2 - 5000) / 13000));
  if (t < 0.5) {
    const u = t * 2;
    return `rgb(${Math.round(59+u*(34-59))},${Math.round(130+u*(197-130))},${Math.round(246+u*(94-246))})`;
  } else {
    const u = (t - 0.5) * 2;
    return `rgb(${Math.round(34+u*(239-34))},${Math.round(197+u*(68-197))},${Math.round(94+u*(68-94))})`;
  }
}
function insColorRatio(ratio) {
  if (!ratio) return '#94a3b8';
  if (ratio >= 1.3)  return '#15803d';
  if (ratio >= 1.1)  return '#22c55e';
  if (ratio >= 1.0)  return '#86efac';
  if (ratio >= 0.92) return '#94a3b8';
  if (ratio >= 0.85) return '#f97316';
  return '#ef4444';
}
function insColorScore(score) {
  if (!score) return '#94a3b8';
  if (score >= 75) return '#22c55e';
  if (score >= 55) return '#f59e0b';
  return '#ef4444';
}
function insGetColor(d) {
  if (_insMetric === 'pm2')   return insColorPM2(d.pm2);
  if (_insMetric === 'ratio') return (d.avm_qualified&&d.avm_ratio)?insColorRatio(d.avm_ratio):'#cbd5e1';
  return insColorScore(d.score);
}

function loadInsLeaflet() {
  if (typeof L !== 'undefined') { renderInsMap(); return; }
  if (!document.getElementById('leaflet-css')) {
    const l = document.createElement('link');
    l.id = 'leaflet-css'; l.rel = 'stylesheet';
    l.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(l);
  }
  if (!document.getElementById('leaflet-js')) {
    const s = document.createElement('script');
    s.id = 'leaflet-js';
    s.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    s.onload = renderInsMap;
    document.body.appendChild(s);
  }
}

function renderInsMap() {
  const mapEl = document.getElementById('ins-map');
  if (!mapEl || typeof L === 'undefined') return;
  const data = window._insData || [];

  // Filter by type
  let pts = data;
  if (_insMapType === 'appart') pts = data.filter(d=>d.type==='appart');
  if (_insMapType === 'maison') pts = data.filter(d=>d.type==='maison');

  // Group by location key to compute jitter
  const groups = {};
  pts.forEach(d => {
    const key = d.type==='maison' ? (d.section||'G') : (d.location||'Chamonix');
    if (!groups[key]) groups[key] = [];
    groups[key].push(d);
  });

  // Init or reset map
  if (_insLeaflet) {
    _insLeaflet.eachLayer(l => { if (l instanceof L.CircleMarker) _insLeaflet.removeLayer(l); });
    _insLeaflet.eachLayer(l => { if (l._url && l._url.includes('tile')) return; _insLeaflet.removeLayer(l); });
  } else {
    _insLeaflet = L.map('ins-map', {center:[45.930,6.820],zoom:11,zoomControl:true});
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
      attribution:'© OpenStreetMap','maxZoom':18}).addTo(_insLeaflet);
  }

  // Clear circle markers
  if (_insLeaflet._layers) {
    Object.values(_insLeaflet._layers).forEach(l => {
      if (l instanceof L.CircleMarker) _insLeaflet.removeLayer(l);
    });
  }

  // Add markers
  let minPM2=Infinity,maxPM2=-Infinity;
  pts.forEach(d=>{if(d.pm2){minPM2=Math.min(minPM2,d.pm2);maxPM2=Math.max(maxPM2,d.pm2);}});

  Object.entries(groups).forEach(([key, items]) => {
    items.forEach((d, idx) => {
      const [lat, lon] = getInsCoords(d, idx, items.length);
      const color = insGetColor(d);
      const r     = d.type==='maison' ? 9 : 7;
      const shape = d.type==='maison' ? 4 : 0; // 4=square via custom icon, 0=circle

      const circle = L.circleMarker([lat, lon], {
        radius: r,
        fillColor: color,
        color: '#fff',
        weight: 1.5,
        opacity: 1,
        fillOpacity: 0.85,
      });

      const pct = d.avm_ratio&&d.avm_qualified?`<br>Ratio AVM : <strong>×${d.avm_ratio.toFixed(2)}</strong>`:'';
      const avmStr = d.avm_pred&&d.avm_qualified?`<br>AVM : ${(d.avm_pred/1e3).toFixed(0)}k€${pct}`:'';
      const icon = d.type==='maison'?'🏠':'🏢';
      circle.bindPopup(`
        <div style="font-size:.82rem;min-width:180px">
          <div style="font-weight:700;margin-bottom:4px">${icon} ${(d.label||'').substring(0,32)}</div>
          <div>Prix : <strong>${(d.prix/1e3).toFixed(0)}k€</strong> · ${Math.round(d.surface)}m²</div>
          <div>PM2 : ${Math.round(d.pm2).toLocaleString('fr-FR')} €/m²</div>
          ${avmStr}
          ${d.url?`<div style="margin-top:5px"><a href="${d.url}" target="_blank" style="color:#3b82f6">Voir l'annonce →</a></div>`:''}
        </div>
      `);
      circle.addTo(_insLeaflet);
    });
  });

  // Invalidate size (fix display after tab switch)
  setTimeout(()=>_insLeaflet.invalidateSize(),150);

  // Legend
  const legEl = document.getElementById('ins-map-legend');
  if (legEl) {
    if (_insMetric==='pm2') {
      legEl.innerHTML = `
        <span style="font-weight:600;color:var(--muted)">€/m² :</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#3b82f6"></span>&lt;8k</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#22c55e"></span>10-12k</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#f97316"></span>14-16k</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#ef4444"></span>&gt;16k</span>
        <span style="margin-left:auto">🔵 Appart · ◉ Maison (plus grand)</span>`;
    } else if (_insMetric==='ratio') {
      legEl.innerHTML = `
        <span style="font-weight:600;color:var(--muted)">Ratio AVM :</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#15803d"></span>&gt;1.30 ✅</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#22c55e"></span>1.10-1.30</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#94a3b8"></span>≈marché</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#ef4444"></span>surcôté</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#cbd5e1"></span>pas d'AVM</span>`;
    } else {
      legEl.innerHTML = `
        <span style="font-weight:600;color:var(--muted)">Score :</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#22c55e"></span>≥75</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#f59e0b"></span>55-74</span>
        <span class="ins-map-legend-item"><span class="ins-map-legend-dot" style="background:#ef4444"></span>&lt;55</span>`;
    }
  }
}
"""

# ─── Injection CSS ────────────────────────────────────────────────────────────
html = html.replace('</style>', CSS + '\n</style>', 1)
print("CSS injecté")

# ─── Injection JS : remplacer buildInsights() + fonctions ins* ────────────────
# Supprimer l'ancienne version complète (de "// ═══ INSIGHTS V2" jusqu'au prochain
# gros bloc ou fin de script)

# Chercher le début de la zone insights v2
patterns = [
    r'// ═+\s*\nINSIGHTS V2\n// ═+.*?(?=\n// ═|\n</script>)',
    r'// ═+\s*\n// INSIGHTS V2.*?(?=\n// ═|\n</script>)',
    r'let _insType = .all.;.*?(?=\n// ═|\nfunction buildComparateur)',
]
replaced = False
for pat in patterns:
    m = re.search(pat, html, re.DOTALL)
    if m:
        html = html[:m.start()] + JS.strip() + html[m.end():]
        print(f"buildInsights v2 remplacé (pattern: {pat[:40]})")
        replaced = True
        break

if not replaced:
    # Chercher function buildInsights spécifiquement et remplacer le bloc
    m = re.search(r'function buildInsights\(\)\s*\{', html)
    if m:
        # Trouver la fin du bloc (brace matching)
        start = m.start()
        depth = 0
        i = m.start()
        in_fn = False
        while i < len(html):
            if html[i] == '{':
                depth += 1
                in_fn = True
            elif html[i] == '}':
                depth -= 1
                if in_fn and depth == 0:
                    end = i + 1
                    break
            i += 1
        # Aussi supprimer les fonctions ins* qui suivent
        # Trouver tout le bloc jusqu'à la prochaine fonction principale
        end_extended = re.search(r'\nfunction (?!ins|renderInsMap|loadInsLeaflet|getInsCoords|insColor|insGet)', html[end:])
        if end_extended:
            end = end + end_extended.start()
        html = html[:start] + JS.strip() + '\n' + html[end:]
        print("buildInsights remplacée par v3 (brace matching)")
        replaced = True

if not replaced:
    # Fallback : injecter avant </script>
    html = html.replace('</script>', JS.strip() + '\n</script>', 1)
    print("JS injecté en fallback (avant </script>)")

# ─── Sauvegarde ───────────────────────────────────────────────────────────────
DASH.write_text(html, encoding="utf-8")
size_kb = len(html) // 1024
print(f"\ndashboard.html mis à jour ({size_kb} KB)")
print("✅ Insights v3 injecté :")
print("   → Filter Tous/Apparts/Maisons")
print("   → KPI row (fraîcheur <7j)")
print("   → PM2 bar chart par commune")
print("   → AVM distribution + scatter (Cham/Arg only)")
print("   → Top 8 opportunités")
print("   → Tableau comparatif par commune")
print("   → Heatmap Leaflet (lazy CDN, sunflower jitter)")
print("   → Metric toggle: PM2 / Ratio AVM / Score")
print("   → Coverage note précise")
