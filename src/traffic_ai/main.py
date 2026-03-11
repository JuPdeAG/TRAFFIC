"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from traffic_ai.config import settings
from traffic_ai.db.database import init_db, close_db
from traffic_ai.api.routes import health, segments, risk, predictions, assets, tickets, auth as auth_routes

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
app.include_router(health.router, tags=["Health"])
app.include_router(auth_routes.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(segments.router, prefix="/api/v1", tags=["Segments"])
app.include_router(risk.router, prefix="/api/v1", tags=["Risk"])
app.include_router(predictions.router, prefix="/api/v1", tags=["Predictions"])
app.include_router(assets.router, prefix="/api/v1", tags=["Assets"])
app.include_router(tickets.router, prefix="/api/v1", tags=["Tickets"])
