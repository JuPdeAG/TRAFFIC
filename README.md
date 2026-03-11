# Traffic AI Platform

**Hardware-adaptive intelligent transportation system** for real-time traffic risk assessment, congestion prediction, and road infrastructure monitoring.

## Architecture Overview

```
┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│   FastAPI     │    │   Celery     │    │  Celery Beat │
│   API Server  │    │   Workers    │    │  Scheduler   │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                    │
       ├───────────────────┼────────────────────┘
       │                   │
  ┌────▼────┐    ┌────────▼────────┐    ┌────────────┐
  │PostgreSQL│    │    InfluxDB     │    │   Redis     │
  │(PostGIS) │    │  (Time Series)  │    │  (Broker)   │
  └─────────┘    └─────────────────┘    └────────────┘
```

### Core Services
- **API Server** — FastAPI with JWT authentication, CRUD endpoints, risk scoring
- **Celery Workers** — Async task processing for data ingestion and analytics
- **Celery Beat** — Scheduled tasks (sensor polling, weather updates, baseline recalculation)
- **PostgreSQL + PostGIS** — Primary datastore with spatial queries
- **InfluxDB** — Time-series storage for sensor readings and weather data
- **Redis** — Celery broker and result backend
- **Flower** — Celery monitoring dashboard

### Hardware-Adaptive Profiles
The platform supports 5 resource profiles: `lite`, `balanced`, `prosumer`, `full`, `benchmark`. Each profile configures concurrency limits, polling intervals, and GPU enablement based on available hardware.

## Quick Start

```bash
# Clone and configure
cp .env.example .env
# Edit .env with your settings (especially SECRET_KEY)

# Start all services
docker compose up -d

# Verify
curl http://localhost:8000/api/v1/health
```

The API will be available at `http://localhost:8000`.

### Prosumer Profile

For prosumer deployments with GPU support:

```bash
docker compose -f docker-compose.yml -f docker-compose.prosumer.yml up -d
```

## API Documentation

Once running, interactive API docs are available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints
| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/auth/token` | Obtain JWT access token |
| `GET /api/v1/segments` | List road segments |
| `GET /api/v1/risk/{segment_id}` | Get risk score for a segment |
| `GET /api/v1/risk/summary` | Risk summary for all segments |
| `POST /api/v1/predict/congestion` | Predict congestion (LSTM pending) |
| `GET /api/v1/assets` | List road assets |
| `GET /api/v1/tickets` | List maintenance tickets |
| `GET /api/v1/health` | Health check (public) |
| `GET /api/v1/ready` | Readiness check (public) |

## Development Setup

```bash
# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Install ML dependencies (optional)
pip install -e ".[ml]"
```

## Testing

```bash
# Run unit tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Note: DB-dependent tests require a running PostgreSQL+PostGIS instance
# Set TEST_DATABASE_URL env var to point to a test database
```

## Environment Variables

See `.env.example` for all available configuration options. Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `PROFILE` | Hardware profile | `balanced` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://...` |
| `SECRET_KEY` | JWT signing key | `change-me` |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `LOOP_DETECTOR_URLS` | Comma-separated detector URLs | `` |
| `NOAA_STATIONS` | Comma-separated NOAA station IDs | `` |
| `AEMET_STATIONS` | Comma-separated AEMET station IDs | `` |

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes with clear messages
4. Ensure all tests pass (`pytest`)
5. Submit a pull request

Please follow the existing code style and add tests for new functionality.
