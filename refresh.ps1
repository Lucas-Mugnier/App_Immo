# refresh.ps1 — met à jour les annonces du site, depuis ce PC.
#
#   .\refresh.ps1                      # scrape tout + export + publication
#   .\refresh.ps1 --skip-scrape        # ré-export + publication sans re-scraper
#   .\refresh.ps1 --commune chamonix   # (options passées à pipeline.py)
#
# Prérequis (une fois) : pip install -r requirements.txt ; cd dashboard-react ; npm install
#                         dashboard-react\.env.publish rempli (cf. .env.publish.example)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host "== 1/2 Scraping + export ==" -ForegroundColor Cyan
python pipeline.py @args
if ($LASTEXITCODE -ne 0) { throw "pipeline.py a échoué (code $LASTEXITCODE)" }

Write-Host "== 2/2 Publication vers Supabase (bucket privé) ==" -ForegroundColor Cyan
Push-Location dashboard-react
try {
  node scripts/publish-data.mjs
  if ($LASTEXITCODE -ne 0) { throw "publish-data.mjs a échoué (code $LASTEXITCODE)" }
} finally { Pop-Location }

$changed = git status --porcelain -- dashboard-react/src/data
if ($changed) {
  Write-Host ""
  Write-Host "Les données PUBLIQUES (DVF / agrégats) ont changé :" -ForegroundColor Yellow
  Write-Host $changed
  Write-Host "→ git add dashboard-react/src/data ; git commit -m 'data: refresh' ; git push   (redéploie le site)"
} else {
  Write-Host "Annonces à jour en ligne. Aucune donnée publique modifiée, pas besoin de redéployer." -ForegroundColor Green
}
