# ============================================================
#  Traffic AI — local development startup
#  Usage: .\dev.ps1
#
#  What this does:
#    1. Starts infrastructure in Docker (Postgres, Redis, InfluxDB)
#    2. Creates a Python venv if one doesn't exist
#    3. Installs Python deps
#    4. Copies .env if missing and reminds you to fill it in
#    5. Runs Alembic migrations (or stamps if schema already exists)
#    6. Opens three new terminal windows:
#         - FastAPI (uvicorn, hot-reload)
#         - Celery worker
#         - React dev server (Vite)
# ============================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ROOT = $PSScriptRoot

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    [!!] $msg" -ForegroundColor Yellow }

# ── 1. Check Docker is running ───────────────────────────────
Write-Step "Checking Docker..."
try {
    docker info | Out-Null
    Write-OK "Docker is running"
} catch {
    Write-Host "Docker is not running. Start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

# ── 2. Start infrastructure (not the app containers) ─────────
Write-Step "Starting infrastructure services (postgres, redis, influxdb)..."
docker compose -f "$ROOT\docker-compose.yml" up -d postgres redis influxdb
Write-OK "Infrastructure containers started"

# ── 3. Wait for Postgres to be healthy ───────────────────────
Write-Step "Waiting for Postgres to be ready..."
$attempts = 0
do {
    Start-Sleep -Seconds 2
    $attempts++
    $health = docker inspect --format="{{.State.Health.Status}}" traffic_plus-postgres-1 2>$null
    if (-not $health) {
        # container name may vary slightly
        $health = docker compose ps --format json | ConvertFrom-Json |
                  Where-Object { $_.Service -eq "postgres" } |
                  Select-Object -ExpandProperty Health -ErrorAction SilentlyContinue
    }
} while ($health -ne "healthy" -and $attempts -lt 30)

if ($attempts -ge 30) {
    Write-Warn "Postgres didn't become healthy in time. Check: docker compose logs postgres"
} else {
    Write-OK "Postgres is healthy"
}

# ── 4. .env setup ────────────────────────────────────────────
Write-Step "Checking .env..."
if (-not (Test-Path "$ROOT\.env")) {
    Copy-Item "$ROOT\.env.example" "$ROOT\.env"
    Write-Warn ".env created from .env.example — open it and set SECRET_KEY, INFLUX_TOKEN, etc."
    Write-Warn "Press Enter to continue once you've reviewed it, or Ctrl+C to stop."
    Read-Host
} else {
    Write-OK ".env already exists"
}

# Frontend .env
if (-not (Test-Path "$ROOT\frontend\.env")) {
    Copy-Item "$ROOT\frontend\.env.example" "$ROOT\frontend\.env"
    Write-OK "frontend/.env created (VITE_API_URL=http://localhost:8000)"
} else {
    Write-OK "frontend/.env already exists"
}

# ── 5. Python venv ────────────────────────────────────────────
Write-Step "Setting up Python virtual environment..."
if (-not (Test-Path "$ROOT\.venv")) {
    python -m venv "$ROOT\.venv"
    Write-OK "Created .venv"
} else {
    Write-OK ".venv already exists"
}

$pip  = "$ROOT\.venv\Scripts\pip.exe"
$python = "$ROOT\.venv\Scripts\python.exe"
$alembic = "$ROOT\.venv\Scripts\alembic.exe"
$uvicorn = "$ROOT\.venv\Scripts\uvicorn.exe"
$celery  = "$ROOT\.venv\Scripts\celery.exe"

Write-Step "Installing Python dependencies..."
& $pip install -e "$ROOT[dev]" -q
Write-OK "Dependencies installed"

# ── 6. Alembic migrations ─────────────────────────────────────
Write-Step "Running database migrations..."
# init_db.sql may have already created tables — if so, just stamp
$env:PYTHONPATH = "$ROOT\src"

# Load DATABASE_URL from .env for the migration
$envVars = Get-Content "$ROOT\.env" | Where-Object { $_ -match "^[A-Z_]+=.+" }
foreach ($line in $envVars) {
    $parts = $line -split "=", 2
    [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
}

try {
    & $alembic -c "$ROOT\alembic.ini" upgrade head 2>&1 | Tee-Object -Variable migrateOut | Out-Null
    if ($migrateOut -match "already exists") {
        & $alembic -c "$ROOT\alembic.ini" stamp head | Out-Null
        Write-OK "Schema already exists — stamped Alembic to current head"
    } else {
        Write-OK "Migrations applied"
    }
} catch {
    Write-Warn "Migration step had an issue: $_"
    Write-Warn "You may need to run manually: alembic upgrade head"
}

# ── 7. Frontend dependencies ──────────────────────────────────
Write-Step "Installing frontend dependencies..."
Push-Location "$ROOT\frontend"
npm install --silent
Pop-Location
Write-OK "Frontend dependencies ready"

# ── 8. Launch dev processes in new windows ────────────────────
Write-Step "Launching dev servers..."

# FastAPI
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$ROOT'; `$env:PYTHONPATH='$ROOT\src'; " +
    "& '$uvicorn' traffic_ai.main:app --reload --host 0.0.0.0 --port 8000"
) -WindowStyle Normal

# Celery worker
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$ROOT'; `$env:PYTHONPATH='$ROOT\src'; " +
    "& '$celery' -A traffic_ai.celery_app worker --loglevel=info --concurrency=2"
) -WindowStyle Normal

# Vite dev server
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$ROOT\frontend'; npm run dev"
) -WindowStyle Normal

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Dev environment is up!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "  API:       http://localhost:8000"
Write-Host "  API docs:  http://localhost:8000/docs"
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  Flower:    run 'docker compose up -d flower' to enable"
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "To stop infrastructure: .\dev-stop.ps1" -ForegroundColor Gray
