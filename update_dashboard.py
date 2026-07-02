#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_dashboard.py — Injecte dvf_stats.json dans data.json du dashboard
Usage: C:/Users/lucas/anaconda3/python.exe update_dashboard.py

A lancer apres dvf_pipeline.py [--geo] et dvf_model.py
"""
import json
import os
import sys

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DVF_STATS_PATH = os.path.join(BASE_DIR, "dvf", "dvf_stats.json")
DATA_JSON_PATH = os.path.join(BASE_DIR, "..", "appart-alert-dashboard-v2", "public", "data.json")

print("Injection dvf_stats -> data.json...")

if not os.path.exists(DVF_STATS_PATH):
    print(f"ERREUR: {DVF_STATS_PATH} introuvable")
    print("Lancer d'abord: python dvf_pipeline.py && python dvf_model.py")
    sys.exit(1)

if not os.path.exists(DATA_JSON_PATH):
    print(f"ERREUR: {DATA_JSON_PATH} introuvable")
    sys.exit(1)

with open(DVF_STATS_PATH, encoding="utf-8") as f:
    dvf_stats = json.load(f)

with open(DATA_JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)

data["dvf_stats"] = dvf_stats

with open(DATA_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

# Résumé
model = dvf_stats.get("model", {})
total = dvf_stats.get("total_transactions", 0)
communes = list(dvf_stats.get("communes", {}).keys())
geo_feats = model.get("geo_features", [])

print(f"OK data.json mis a jour")
print(f"  {total:,} transactions | {len(communes)} communes")
print(f"  model R2_cv={model.get('r2_cv', '?')}")
if model.get('r2_cv_base'):
    print(f"  (base sans geo: {model['r2_cv_base']})")
if geo_feats:
    print(f"  geo features: {geo_feats}")
print(f"  MAE={model.get('mae_eur', '?')} e/m2")
print(f"\n  Chemin: {DATA_JSON_PATH}")
print("\nPensez a relancer npm run build dans le dashboard si vous deployez.")
