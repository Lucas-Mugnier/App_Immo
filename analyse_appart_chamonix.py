"""
analyse_appart_chamonix.py
===========================
Analyse exploratoire + modele AVM — Appartements Chamonix
Filtres : PM2_MIN=6000 + PM2_MAX=20000 + bundle split
(memes features que maisons, sans terrain)
Output : dvf/appart_chamonix_diagnostic.html
"""

import pandas as pd
import numpy as np
import json, pickle
from pathlib import Path
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

BASE = Path(__file__).parent
DVF  = BASE / "dvf"

# ─────────────────────────────────────────────
# 1. CHARGEMENT + FILTRES
# ─────────────────────────────────────────────
PM2_MIN = 8_000   # marche reel : ancien bon etat 10-12k, neuf haut de gamme jusqu'a 16k
PM2_MAX = 18_000  # cap reel : au-dela = ultra-premium anecdotique (luxe = chalets)

df  = pd.read_csv(DVF / "dvf_clean.csv")
raw = df[(df["type_local"]=="appart") & (df["commune"]=="CHAMONIX MONT BLANC")].copy()
raw = raw.dropna(subset=["valeur","surface"]).reset_index(drop=True)
N_RAW = len(raw)
raw["pm2"] = raw["valeur"] / raw["surface"]

# Filtre bundle split : meme date+voie, ratio vs PM2 pondere < 0.25 ou > 4
raw["bkey"] = raw["date"].astype(str) + "|" + raw["voie"].astype(str)
bpm2 = raw.groupby("bkey").apply(lambda x: x["valeur"].sum() / x["surface"].sum())
bcnt = raw.groupby("bkey").size()
raw["in_bun"] = raw["bkey"].map(bcnt) >= 2
raw["bpm2w"]  = raw["bkey"].map(bpm2)
raw["rb"]     = raw["pm2"] / raw["bpm2w"]
f_bundle = raw["in_bun"] & ((raw["rb"] < 0.25) | (raw["rb"] > 4.0))

# Filtres PM2
f_pm2 = (raw["pm2"] < PM2_MIN) | (raw["pm2"] > PM2_MAX)

# Filtre terrain : exclure apparts avec du terrain associe (maisons mal codees)
f_terrain = raw["surf_terrain"].fillna(0) > 0

n_bundle  = f_bundle.sum()
n_pm2     = f_pm2.sum()
n_terrain = f_terrain.sum()
pre_clean = raw[~f_bundle & ~f_pm2 & ~f_terrain].copy().reset_index(drop=True)

# Filtre lot-agrege : nb_lots>=2 ET PM2 < 75% mediane voie
# -> surface sommee de plusieurs lots mais prix = 1 seul bien (bug DVF)
voie_med_pre          = pre_clean.groupby("voie")["pm2"].median()
pre_clean["pm2_voie_med"]   = pre_clean["voie"].map(voie_med_pre)
pre_clean["pm2_ratio_voie"] = pre_clean["pm2"] / pre_clean["pm2_voie_med"]
f_lot_bug = (pre_clean["nb_lots"].fillna(1) >= 2) & (pre_clean["pm2_ratio_voie"] < 0.75)
n_lot_bug = f_lot_bug.sum()

clean = pre_clean[~f_lot_bug].copy().reset_index(drop=True)
N_CLEAN = len(clean)

print(f"  Bundle split enleve : {n_bundle}")
print(f"  PM2 hors [{PM2_MIN}-{PM2_MAX}]  : {n_pm2}")
print(f"  Avec terrain        : {n_terrain}")
print(f"  Lot-agrege bug      : {n_lot_bug}")
print(f"  Reste apres filtres  : {N_CLEAN}")

SEC_LABELS = {"A":"La Tour","B":"Argentiere","C":"Les Praz/Tines","D":"Centre est","E":"Les Bossons","G":"Moussoux/Centre"}
SEC_COLORS = {"A":"#6366f1","B":"#22c55e","C":"#f59e0b","D":"#3b82f6","E":"#ec4899","G":"#ef4444"}

print(f"Chamonix apparts brut (sans null) : {N_RAW}")
print(f"Sections : {clean['section'].value_counts().to_dict()}")
print(f"\nSurface  min={clean['surface'].min():.0f}  max={clean['surface'].max():.0f}  med={clean['surface'].median():.0f}")
print(f"PM2      min={clean['pm2'].min():.0f}  max={clean['pm2'].max():.0f}  med={clean['pm2'].median():.0f}")

# ─────────────────────────────────────────────
# 2. STATS PAR SECTION
# ─────────────────────────────────────────────
sec_stats = clean.groupby("section").agg(
    n=("pm2","count"),
    med=("pm2","median"),
    mean=("pm2","mean"),
    std=("pm2","std"),
    p10=("pm2", lambda x: np.percentile(x,10)),
    p90=("pm2", lambda x: np.percentile(x,90)),
).round(0)
print("\nStats pm2 par section (sans filtre):")
print(sec_stats)

# ─────────────────────────────────────────────
# 3. MODELE XGBoost — memes features que maisons sans terrain
# ─────────────────────────────────────────────
ANNEE_REF = 2024
le_sec = LabelEncoder()
clean["sec_enc"]  = le_sec.fit_transform(clean["section"])
clean["log_surf"] = np.log(clean["surface"].clip(1))
clean["pieces_f"] = clean["pieces"].fillna(2.0).clip(1,10)
clean["annee_f"]  = (clean["annee"] - ANNEE_REF).astype(float)
clean["ndep_f"]   = clean["n_dependances"].clip(0,5).astype(float)
clean["lots_f"]   = clean["nb_lots"].clip(0,4).astype(float)
med_lat  = clean["lat"].dropna().median()
med_lon  = clean["lon"].dropna().median()
med_alt  = clean["altitude"].dropna().median()
med_dist = clean["dist_centre_km"].dropna().median()
med_ski  = clean["dist_ski_lift_km"].dropna().median()
clean["lat_f"]  = clean["lat"].fillna(med_lat).astype(float)
clean["lon_f"]  = clean["lon"].fillna(med_lon).astype(float)
clean["alt_f"]  = clean["altitude"].fillna(med_alt).astype(float)
clean["dist_f"] = clean["dist_centre_km"].fillna(med_dist).astype(float)
clean["ski_f"]  = clean["dist_ski_lift_km"].fillna(med_ski).astype(float)

FEATS = ["log_surf","pieces_f","sec_enc","annee_f","ndep_f","lots_f","alt_f","dist_f","ski_f","lat_f","lon_f"]
X = clean[FEATS].astype(float)
y = np.log(clean["valeur"])

xgb = XGBRegressor(n_estimators=400, max_depth=5, learning_rate=0.04,
                   subsample=0.8, colsample_bytree=0.8,
                   min_child_weight=5, reg_alpha=0.1, reg_lambda=1.0,
                   random_state=42, n_jobs=-1, verbosity=0)

kf = KFold(n_splits=5, shuffle=True, random_state=42)
# ── Passe 1 : CV sur base filtrée (PM2 + bundle + terrain + lot-bug) ──
y_cv_p1 = cross_val_predict(xgb, X, y, cv=kf)
clean["ratio_p1"] = np.exp(y_cv_p1) / clean["valeur"]
mape_p1 = mean_absolute_percentage_error(clean["valeur"], np.exp(y_cv_p1))
print(f"\nPasse 1 (avant ratio-clip) : MAPE {mape_p1:.1%}  n={len(clean)}")

# ── Ratio-clip [0.80-1.25] : retire premium (>12k/m2) + ventes anomalies ──
RATIO_LO, RATIO_HI = 0.80, 1.25
f_ratio  = (clean["ratio_p1"] < RATIO_LO) | (clean["ratio_p1"] > RATIO_HI)
n_lo     = (clean["ratio_p1"] < RATIO_LO).sum()
n_hi     = (clean["ratio_p1"] > RATIO_HI).sum()
print(f"Ratio-clip [{RATIO_LO}-{RATIO_HI}] : -{f_ratio.sum()} tx ({n_lo} premium + {n_hi} anomalies)")
clean    = clean[~f_ratio].copy().reset_index(drop=True)
N_CLEAN  = len(clean)

# Recompute features sur le sous-ensemble clean
clean["sec_enc"]  = le_sec.transform(clean["section"])
clean["log_surf"] = np.log(clean["surface"].clip(1))
clean["pieces_f"] = clean["pieces"].fillna(2.0).clip(1,10)
clean["annee_f"]  = (clean["annee"] - ANNEE_REF).astype(float)
clean["ndep_f"]   = clean["n_dependances"].clip(0,5).astype(float)
clean["lots_f"]   = clean["nb_lots"].clip(0,4).astype(float)
clean["lat_f"]    = clean["lat"].fillna(med_lat).astype(float)
clean["lon_f"]    = clean["lon"].fillna(med_lon).astype(float)
clean["alt_f"]    = clean["altitude"].fillna(med_alt).astype(float)
clean["dist_f"]   = clean["dist_centre_km"].fillna(med_dist).astype(float)
clean["ski_f"]    = clean["dist_ski_lift_km"].fillna(med_ski).astype(float)
X = clean[FEATS].astype(float)
y = np.log(clean["valeur"])

# ── Passe 2 : CV + entraînement final sur données nettoyées ──
y_cv = cross_val_predict(xgb, X, y, cv=kf)
clean["pred_cv"]  = np.exp(y_cv)
clean["err_pct"]  = (clean["pred_cv"] - clean["valeur"]).abs() / clean["valeur"]
clean["err_sign"] = (clean["pred_cv"] - clean["valeur"]) / clean["valeur"]
clean["ratio_cv"] = clean["pred_cv"] / clean["valeur"]

mape_cv = mean_absolute_percentage_error(clean["valeur"], clean["pred_cv"])
r2_cv   = r2_score(y, y_cv)
p50 = np.percentile(clean["err_pct"], 50)
p80 = np.percentile(clean["err_pct"], 80)

print(f"Passe 2 (apres  ratio-clip) : MAPE {mape_cv:.1%}  R2 {r2_cv:.3f}  P50 {p50:.1%}  P80 {p80:.1%}")

xgb.fit(X, y)
clean["pred_train"] = np.exp(xgb.predict(X))

# Index inflation + PM2 recents
emp = clean.groupby("annee")["pm2"].median()
emp_idx = (emp / emp[ANNEE_REF]).round(4).to_dict()
years = sorted(emp_idx.keys())
if len(years) >= 3:
    trend = emp_idx[years[-1]] - emp_idx[years[-2]]
    emp_idx[2026] = round(emp_idx[years[-1]] + trend, 4)
recent = clean[clean["annee"] >= 2023]
pm2_sec = recent.groupby("section")["pm2"].median().round(0).to_dict()
pm2_global = int(recent["pm2"].median())

voie_stats = clean.groupby("voie").agg(n=("pm2","count"), med=("pm2","median")).query("n>=5").sort_values("med",ascending=False)

# ─────────────────────────────────────────────
# 4. GRAPHIQUES
# ─────────────────────────────────────────────
figs = []

# ── Fig 1 : Distribution prix/m² brut avec curseurs outliers ──
fig1 = go.Figure()
fig1.add_trace(go.Histogram(x=clean["pm2"], nbinsx=80,
    marker_color="#3b82f6", opacity=0.75, name="Prix/m2"))
# Reperes visuels
for x_line, label, color in [(PM2_MIN,f"{PM2_MIN:,} (seuil bas)","orange"),
                               (PM2_MAX,f"{PM2_MAX:,} (seuil haut)","red"),
                               (clean["pm2"].median(),"Mediane","green")]:
    fig1.add_vline(x=x_line, line_dash="dash", line_color=color,
                   annotation_text=label, annotation_position="top right")
fig1.update_layout(title=f"Distribution prix/m2 — {N_CLEAN} transactions (PM2 {PM2_MIN:,}-{PM2_MAX:,})",
    height=420, xaxis_title="EUR/m2", yaxis_title="Nb transactions")
figs.append(("EUR/m2 distribution", fig1))

# ── Fig 2 : Distribution surface brut ──
fig2 = go.Figure()
fig2.add_trace(go.Histogram(x=clean["surface"], nbinsx=80,
    marker_color="#22c55e", opacity=0.75))
for x_line, label in [(14,"14m2 (seuil caves)"),(120,"120m2 (ancien seuil)"),(200,"200m2")]:
    fig2.add_vline(x=x_line, line_dash="dash", line_color="orange",
                   annotation_text=label)
fig2.update_layout(title=f"Distribution surfaces BRUT — {N_RAW} transactions",
    height=400, xaxis_title="Surface m2")
figs.append(("Surface distribution", fig2))

# ── Fig 3 : Scatter surface vs prix/m2 (pour voir les outliers) ──
fig3 = go.Figure()
for sec in sorted(clean["section"].unique()):
    grp = clean[clean["section"]==sec]
    fig3.add_trace(go.Scatter(
        x=grp["surface"], y=grp["pm2"],
        mode="markers", name=f"Sec {sec} — {SEC_LABELS.get(sec,sec)}",
        marker=dict(color=SEC_COLORS.get(sec,"#888"), size=5, opacity=0.55),
        hovertemplate=(
            "Surface: %{x}m2<br>PM2: %{y:,.0f}EUR<br>"
            "Valeur: %{customdata[0]:,.0f}EUR<br>"
            "Voie: %{customdata[1]}<br>Annee: %{customdata[2]}"
            "<extra>Sec " + sec + "</extra>"
        ),
        customdata=grp[["valeur","voie","annee"]].values
    ))
fig3.update_layout(title="Surface vs Prix/m2 (tous outliers visibles)",
    height=550, xaxis_title="Surface m2", yaxis_title="EUR/m2", hovermode="closest")
figs.append(("Surface vs PM2", fig3))

# ── Fig 4 : Boxplot pm2 par section ──
fig4 = go.Figure()
for sec in sorted(clean["section"].unique()):
    grp = clean[clean["section"]==sec]["pm2"]
    fig4.add_trace(go.Box(y=grp, name=f"{sec} — {SEC_LABELS.get(sec,sec)} ({len(grp)})",
        marker_color=SEC_COLORS.get(sec,"#888"), boxmean=True))
fig4.update_layout(title="Prix/m2 par section — sans filtre (outliers visibles)",
    height=500, yaxis_title="EUR/m2", showlegend=False)
figs.append(("Boxplot par section", fig4))

# ── Fig 5 : Evolution temporelle ──
fig5 = go.Figure()
pivot = clean.groupby(["annee","section"])["pm2"].agg(["median","count"]).reset_index()
for sec in sorted(pivot["section"].unique()):
    d = pivot[pivot["section"]==sec].sort_values("annee")
    fig5.add_trace(go.Scatter(
        x=d["annee"], y=d["median"], mode="lines+markers",
        name=f"{sec} — {SEC_LABELS.get(sec,sec)}",
        line=dict(color=SEC_COLORS.get(sec,"#888"), width=2),
        marker=dict(size=8),
        text=d["count"].apply(lambda n: f"n={n}"),
        hovertemplate="%{x}: %{y:,.0f}EUR/m2 (%{text})<extra>" + SEC_LABELS.get(sec,sec) + "</extra>"
    ))
global_trend = clean.groupby("annee")["pm2"].median()
fig5.add_trace(go.Scatter(x=global_trend.index, y=global_trend.values, mode="lines",
    name="Mediane globale", line=dict(color="#000", dash="dash", width=1.5)))
fig5.update_layout(title="Evolution pm2 median par section (2021-2025)", height=450,
    yaxis_title="EUR/m2", xaxis_title="Annee", hovermode="x unified")
figs.append(("Evolution temporelle", fig5))

# ── Fig 6 : Scatter valeur vs pred_cv (AVM sans filtre) ──
fig6 = go.Figure()
for sec in sorted(clean["section"].unique()):
    grp = clean[clean["section"]==sec]
    fig6.add_trace(go.Scatter(
        x=grp["valeur"]/1e6, y=grp["pred_cv"]/1e6,
        mode="markers", name=f"Sec {sec}",
        marker=dict(color=SEC_COLORS.get(sec,"#888"), size=5, opacity=0.55),
        hovertemplate=(
            "Reel: %{x:.3f}M<br>AVM: %{y:.3f}M<br>"
            "Voie: %{customdata[0]}<br>Surface: %{customdata[1]}m2<br>"
            "Err: %{customdata[2]:.0f}%"
            "<extra>Sec " + sec + "</extra>"
        ),
        customdata=np.column_stack([grp["voie"], grp["surface"], grp["err_pct"]*100])
    ))
mx = max(clean["valeur"].max(), clean["pred_cv"].max()) / 1e6
fig6.add_trace(go.Scatter(x=[0,mx], y=[0,mx], mode="lines",
    line=dict(color="black", dash="dash", width=1), showlegend=False))
fig6.add_trace(go.Scatter(x=[0,mx], y=[0,mx*1.20], mode="lines",
    line=dict(color="rgba(200,200,200,0.5)", dash="dot", width=1), name="+20%", showlegend=False))
fig6.add_trace(go.Scatter(x=[0,mx], y=[0,mx*0.80], mode="lines",
    line=dict(color="rgba(200,200,200,0.5)", dash="dot", width=1), name="-20%", showlegend=False))
fig6.update_layout(
    title=f"AVM CV vs Prix reel (sans filtre) — MAPE {mape_cv:.1%} R2 {r2_cv:.3f}",
    height=550, xaxis_title="Prix reel (M€)", yaxis_title="Prediction AVM (M€)")
figs.append(("AVM vs Reel", fig6))

# ── Fig 7 : Distribution erreurs CV ──
fig7 = go.Figure()
for sec in sorted(clean["section"].unique()):
    grp = clean[clean["section"]==sec]["err_sign"] * 100
    sec_mape = clean[clean["section"]==sec]["err_pct"].mean() * 100
    fig7.add_trace(go.Violin(y=grp, name=f"{sec} ({sec_mape:.0f}%)",
        marker_color=SEC_COLORS.get(sec,"#888"), box_visible=True, meanline_visible=True, opacity=0.7))
fig7.add_hline(y=0, line_dash="dash", line_color="black")
fig7.add_hrect(y0=-20, y1=20, fillcolor="rgba(34,197,94,0.08)", line_width=0)
fig7.update_layout(title="Distribution erreurs CV par section (% signe)", height=450,
    yaxis_title="Erreur % (AVM-Reel)/Reel")
figs.append(("Erreurs par section", fig7))

# ── Fig 8 : Heatmap section x annee ──
hm = clean.groupby(["section","annee"])["pm2"].median().unstack().round(0)
fig8 = go.Figure(go.Heatmap(
    z=hm.values, x=[str(a) for a in hm.columns],
    y=[f"{s} {SEC_LABELS.get(s,'')}" for s in hm.index],
    colorscale="RdYlGn",
    text=hm.fillna(0).values.round(0).astype(int),
    texttemplate="%{text}", textfont=dict(size=11),
    colorbar=dict(title="EUR/m2"),
    hovertemplate="Section %{y}<br>Annee %{x}<br>%{z:,.0f}EUR/m2<extra></extra>"
))
fig8.update_layout(title="Heatmap pm2 median — Section x Annee", height=350)
figs.append(("Heatmap section x annee", fig8))

# ── Fig 9 : Carte ──
map_data = clean.dropna(subset=["lat","lon"])
fig9 = go.Figure()
for sec in sorted(map_data["section"].unique()):
    grp = map_data[map_data["section"]==sec]
    last = sec == sorted(map_data["section"].unique())[-1]
    fig9.add_trace(go.Scattermapbox(
        lat=grp["lat"], lon=grp["lon"], mode="markers",
        marker=go.scattermapbox.Marker(
            size=7, color=grp["pm2"],
            colorscale="RdYlGn", cmin=4000, cmax=16000,
            showscale=last,
            colorbar=dict(title="EUR/m2") if last else None
        ),
        name=f"Sec {sec}",
        hovertemplate="<b>%{customdata[0]}</b><br>Surface: %{customdata[1]}m2<br>PM2: %{customdata[2]:,.0f}EUR<br>Annee: %{customdata[3]}<extra></extra>",
        customdata=grp[["voie","surface","pm2","annee"]].values
    ))
fig9.update_layout(
    mapbox=dict(style="carto-positron", center=dict(lat=45.924, lon=6.869), zoom=12),
    title="Carte transactions DVF 2021-2025", height=550,
    margin=dict(r=0,t=40,l=0,b=0)
)
figs.append(("Carte", fig9))

# ── Fig 10 : Top voies ──
fig10 = make_subplots(rows=1, cols=2, subplot_titles=["Top 15 residences les + cheres","Top 15 residences les - cheres"])
top15 = voie_stats.head(15)
bot15 = voie_stats.tail(15).sort_values("med")
fig10.add_trace(go.Bar(x=top15["med"], y=top15.index, orientation="h",
    marker_color="#ef4444", text=top15["n"].apply(lambda n: f"n={n}"), textposition="inside"), row=1, col=1)
fig10.add_trace(go.Bar(x=bot15["med"], y=bot15.index, orientation="h",
    marker_color="#22c55e", text=bot15["n"].apply(lambda n: f"n={n}"), textposition="inside"), row=1, col=2)
fig10.update_layout(title="PM2 median par residence (min 5 ventes)", height=500, showlegend=False)
fig10.update_xaxes(title_text="EUR/m2")
figs.append(("Top residences", fig10))

# ─────────────────────────────────────────────
# 5. EXPORT HTML
# ─────────────────────────────────────────────
resume_lines = [
    f"<b>Donnees</b> : {N_RAW} brut → {N_CLEAN} apres filtres — Chamonix 2021-2025",
    f"<b>Filtres</b> : PM2 {PM2_MIN:,}-{PM2_MAX:,} (ancien bon etat → neuf hdg) + bundle split ({n_bundle}) + terrain ({n_terrain}) + lot-agrege bug ({n_lot_bug})",
    f"<b>Surface</b> : min {clean['surface'].min():.0f}m2 / max {clean['surface'].max():.0f}m2 / med {clean['surface'].median():.0f}m2",
    f"<b>PM2</b>     : min {clean['pm2'].min():.0f} / max {clean['pm2'].max():.0f} / med {clean['pm2'].median():.0f} EUR/m2",
    "",
    "<b>Modele AVM XGBoost 5-fold CV</b>",
    f"• MAPE CV : <b>{mape_cv:.1%}</b>",
    f"• R2 CV   : <b>{r2_cv:.3f}</b>",
    f"• Mediane erreur : {p50:.1%} | P80 : {p80:.1%}",
    "",
    "<b>PM2 par section 2023-2025</b>",
] + [f"• Sec {s} — {SEC_LABELS.get(s,s)} : <b>{int(pm2_sec.get(s,0)):,}EUR/m2</b>" for s in sorted(pm2_sec)]

html_parts = ["""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="utf-8">
<title>AVM Appartements Chamonix — Diagnostic PM2_MIN=6000</title>
<style>
  body{font-family:system-ui,sans-serif;margin:0;background:#f8fafc;color:#1e293b}
  header{background:#1e3a5f;color:#fff;padding:18px 32px}
  header h1{margin:0;font-size:1.5rem}
  header p{margin:4px 0 0;opacity:.7;font-size:.9rem}
  .resume{background:#fff;border-radius:12px;padding:20px 28px;margin:20px auto;max-width:1100px;
    box-shadow:0 1px 8px rgba(0,0,0,.07);line-height:1.7}
  .tabs{display:flex;gap:6px;flex-wrap:wrap;padding:0 24px;margin:20px auto;max-width:1100px}
  .tab-btn{padding:8px 16px;border:none;border-radius:8px;background:#e2e8f0;cursor:pointer;
    font-size:.85rem;font-weight:500;transition:background .15s}
  .tab-btn.active,.tab-btn:hover{background:#1e3a5f;color:#fff}
  .chart-panel{display:none;max-width:1100px;margin:0 auto 30px;background:#fff;
    border-radius:12px;padding:12px;box-shadow:0 1px 8px rgba(0,0,0,.07)}
  .chart-panel.active{display:block}
  .kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;
    max-width:1100px;margin:20px auto 0;padding:0 24px}
  .kpi{background:#fff;border-radius:10px;padding:16px 20px;text-align:center;
    box-shadow:0 1px 6px rgba(0,0,0,.07)}
  .kpi-val{font-size:2rem;font-weight:700;color:#1e3a5f}
  .kpi-lbl{font-size:.78rem;color:#64748b;margin-top:4px}
  .warn{background:#fef9c3;border-left:4px solid #ca8a04;padding:10px 16px;border-radius:6px;
    margin:12px 0;font-size:.88rem}
</style></head><body>
<header>
  <h1>AVM Appartements Chamonix — Diagnostic PM2_MIN=6000</h1>
  <p>DVF 2021-2025 · Chamonix uniquement · PM2 6 000-20 000 + bundle split · Memes features que maisons sans terrain</p>
</header>"""]

html_parts.append(f"""
<div class="kpi-grid">
  <div class="kpi"><div class="kpi-val">{N_CLEAN}</div><div class="kpi-lbl">Transactions clean ({N_RAW} brut)</div></div>
  <div class="kpi"><div class="kpi-val">{mape_cv:.1%}</div><div class="kpi-lbl">MAPE CV</div></div>
  <div class="kpi"><div class="kpi-val">{r2_cv:.3f}</div><div class="kpi-lbl">R2 CV</div></div>
  <div class="kpi"><div class="kpi-val">{p50:.1%}</div><div class="kpi-lbl">Erreur mediane</div></div>
  <div class="kpi"><div class="kpi-val">+/-{p80:.1%}</div><div class="kpi-lbl">Fourchette P80</div></div>
  <div class="kpi"><div class="kpi-val">{pm2_global:,}EUR</div><div class="kpi-lbl">PM2 median 23-25</div></div>
</div>
""")

html_parts.append('<div class="resume"><p>' + '<br>'.join(resume_lines) + '</p></div>')

tab_ids = [f"tab_{i}" for i in range(len(figs))]
html_parts.append('<div class="tabs">')
for i,(lbl,_) in enumerate(figs):
    active = ' active' if i==0 else ''
    html_parts.append(f'<button class="tab-btn{active}" onclick="showTab({i})">{lbl}</button>')
html_parts.append('</div>')

import plotly.io as pio
for i,(lbl,fig) in enumerate(figs):
    active = ' active' if i==0 else ''
    chart_html = pio.to_html(fig, full_html=False, include_plotlyjs=(i==0))
    html_parts.append(f'<div id="tab_{i}" class="chart-panel{active}">{chart_html}</div>')

html_parts.append("""
<script>
function showTab(idx){
  document.querySelectorAll('.tab-btn').forEach((b,i)=>b.classList.toggle('active',i===idx));
  document.querySelectorAll('.chart-panel').forEach((p,i)=>p.classList.toggle('active',i===idx));
}
</script>
</body></html>""")

out = DVF / "appart_chamonix_diagnostic.html"
out.write_text("".join(html_parts), encoding="utf-8")
print(f"\nDiagnostic ecrit : {out}")

# Export JSON + PKL
meta = {
    "_desc": f"AVM Appart Chamonix — PM2 {PM2_MIN:,}-{PM2_MAX:,} + bundle — XGBoost 5-fold CV",
    "n_clean": N_CLEAN, "n_raw": N_RAW,
    "mape_cv": round(mape_cv,4), "r2_cv": round(r2_cv,4),
    "p50_err": round(p50,4), "p80_err": round(p80,4),
    "annee_ref": ANNEE_REF,
    "emp_idx": {str(k):v for k,v in emp_idx.items()},
    "pm2_section": {k:int(v) for k,v in pm2_sec.items()},
    "pm2_global_cham": pm2_global,
    "le_section_classes": list(le_sec.classes_),
    "features": FEATS,
    "medians": {"lat":med_lat,"lon":med_lon,"alt":med_alt,"dist":med_dist,"ski":med_ski},
}
(DVF/"avm_appart_cham_meta.json").write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding="utf-8")
with open(DVF/"avm_appart_cham_model.pkl","wb") as f:
    pickle.dump({"model":xgb,"le_sec":le_sec,"features":FEATS,
                 "med":{"lat":med_lat,"lon":med_lon,"alt":med_alt,"dist":med_dist,"ski":med_ski},
                 "annee_ref":ANNEE_REF,"mape_cv":mape_cv,"pm2_sec":pm2_sec},f)
print("JSON + PKL ecrits.")
print(f"PM2 par section (2023-2025): {pm2_sec}")
print(f"Index inflation: {emp_idx}")
