# ============================================================
#  Traffic AI — stop infrastructure
# ============================================================
Write-Host "`n==> Stopping infrastructure containers..." -ForegroundColor Cyan
docker compose stop postgres redis influxdb
Write-Host "    [ok] Done. App processes (uvicorn, celery, vite) close their own windows." -ForegroundColor Green
