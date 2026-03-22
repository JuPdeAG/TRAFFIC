"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from traffic_ai.config import settings
from traffic_ai.db.database import init_db, close_db
from traffic_ai.api.limiter import limiter
from traffic_ai.api.routes import health, segments, risk, predictions, assets, tickets, incidents, auth as auth_routes, cameras, metrics, users, app_settings, map_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialise and tear down resources."""
    await init_db()
    yield
    await close_db()

app = FastAPI(
    title="Traffic AI Platform", version="0.1.0",
    description="Hardware-adaptive intelligent transportation system",
    lifespan=lifespan,
)

# CORS — allow the frontend origin; tighten in production via env var
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(health.router, tags=["Health"])
app.include_router(auth_routes.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(segments.router, prefix="/api/v1", tags=["Segments"])
app.include_router(risk.router, prefix="/api/v1", tags=["Risk"])
app.include_router(predictions.router, prefix="/api/v1", tags=["Predictions"])
app.include_router(assets.router, prefix="/api/v1", tags=["Assets"])
app.include_router(tickets.router, prefix="/api/v1", tags=["Tickets"])
app.include_router(incidents.router, prefix="/api/v1", tags=["Incidents"])
app.include_router(cameras.router, prefix="/api/v1", tags=["Cameras"])
app.include_router(metrics.router, prefix="/api/v1", tags=["Metrics"])
app.include_router(users.router, prefix="/api/v1", tags=["Users"])
app.include_router(app_settings.router, prefix="/api/v1", tags=["Settings"])
app.include_router(map_data.router, prefix="/api/v1", tags=["Map"])
