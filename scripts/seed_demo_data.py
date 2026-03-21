#!/usr/bin/env python3
"""Seed the PostgreSQL database with demo Madrid road segments and an admin user.

Usage:
    python scripts/seed_demo_data.py

Requires DATABASE_URL in environment or a .env file in the project root.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env if python-dotenv is available
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[env] Loaded .env from {env_path}")
    else:
        load_dotenv()
except ImportError:
    pass  # dotenv not installed — rely on os.environ

# ---------------------------------------------------------------------------
# Database URL
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://traffic:traffic@localhost:5432/traffic_ai",
)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
from passlib.context import CryptContext  # noqa: E402

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# SQLAlchemy imports
# ---------------------------------------------------------------------------
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

# Ensure the project src is on sys.path so traffic_ai can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from traffic_ai.models.orm import Base, RoadSegment, User  # noqa: E402

# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------
DEMO_ADMIN = {
    "username": "admin",
    "email": "admin@traffic-ai.local",
    "password": "Traffic2024!",
    "role": "admin",
    "pilot": "default",
    "name": "Demo Admin",
}

# Approximate WKT LINESTRING geometries for Madrid ring road / urban arteries.
# Coordinates are (lon lat) in EPSG:4326.  Each segment is a simplified two-point
# line placed on realistic Madrid positions.
ROAD_SEGMENTS = [
    {
        "id": "m30-n1",
        "name": "M-30 North — A-1 junction",
        "road_class": "motorway",
        "length_m": 2100.0,
        "speed_limit_kmh": 90,
        "lanes": 4,
        "geom_wkt": "LINESTRING(-3.6772 40.4730, -3.6652 40.4910)",
    },
    {
        "id": "m30-ne",
        "name": "M-30 Northeast — Av. de América",
        "road_class": "motorway",
        "length_m": 1800.0,
        "speed_limit_kmh": 90,
        "lanes": 4,
        "geom_wkt": "LINESTRING(-3.6652 40.4910, -3.6430 40.4820)",
    },
    {
        "id": "m30-e",
        "name": "M-30 East — Puente de Vallecas",
        "road_class": "motorway",
        "length_m": 2400.0,
        "speed_limit_kmh": 90,
        "lanes": 3,
        "geom_wkt": "LINESTRING(-3.6430 40.4820, -3.6320 40.4610)",
    },
    {
        "id": "m30-se",
        "name": "M-30 Southeast — Entrevías",
        "road_class": "motorway",
        "length_m": 1950.0,
        "speed_limit_kmh": 90,
        "lanes": 3,
        "geom_wkt": "LINESTRING(-3.6320 40.4610, -3.6470 40.4430)",
    },
    {
        "id": "m30-s",
        "name": "M-30 South — Av. de Córdoba",
        "road_class": "motorway",
        "length_m": 2200.0,
        "speed_limit_kmh": 90,
        "lanes": 4,
        "geom_wkt": "LINESTRING(-3.6470 40.4430, -3.6720 40.4380)",
    },
    {
        "id": "m30-w",
        "name": "M-30 West — Puente de Segovia",
        "road_class": "motorway",
        "length_m": 1600.0,
        "speed_limit_kmh": 80,
        "lanes": 3,
        "geom_wkt": "LINESTRING(-3.7210 40.4560, -3.6960 40.4730)",
    },
    {
        "id": "gran-via",
        "name": "Gran Vía — Callao / Alcalá",
        "road_class": "primary",
        "length_m": 900.0,
        "speed_limit_kmh": 30,
        "lanes": 2,
        "geom_wkt": "LINESTRING(-3.7091 40.4200, -3.6995 40.4197)",
    },
    {
        "id": "castellana-n",
        "name": "Paseo de la Castellana Norte",
        "road_class": "primary",
        "length_m": 3100.0,
        "speed_limit_kmh": 50,
        "lanes": 3,
        "geom_wkt": "LINESTRING(-3.6916 40.4350, -3.6883 40.4630)",
    },
    {
        "id": "av-america",
        "name": "Avenida de América",
        "road_class": "primary",
        "length_m": 1400.0,
        "speed_limit_kmh": 50,
        "lanes": 2,
        "geom_wkt": "LINESTRING(-3.6780 40.4600, -3.6620 40.4680)",
    },
    {
        "id": "calle-alcala",
        "name": "Calle de Alcalá — Retiro",
        "road_class": "secondary",
        "length_m": 1200.0,
        "speed_limit_kmh": 30,
        "lanes": 2,
        "geom_wkt": "LINESTRING(-3.6880 40.4195, -3.6750 40.4185)",
    },
]

# ---------------------------------------------------------------------------
# Alembic migration
# ---------------------------------------------------------------------------

def run_migrations() -> None:
    """Attempt to run alembic upgrade head."""
    alembic_ini = PROJECT_ROOT / "alembic.ini"
    if not alembic_ini.exists():
        print("[migrations] alembic.ini not found — skipping migrations")
        return
    print("[migrations] Running alembic upgrade head …")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("[migrations] OK")
    else:
        print(f"[migrations] alembic exited {result.returncode}:\n{result.stderr.strip()}")
        print("[migrations] Continuing — tables may already exist or will be created below.")


# ---------------------------------------------------------------------------
# Async seeding
# ---------------------------------------------------------------------------

async def seed() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Try to create tables via metadata (fallback if alembic not available)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("[tables] Ensured all tables exist via SQLAlchemy metadata.")
    except Exception as exc:
        print(f"[tables] Warning: {exc}")

    created_segments = 0
    skipped_segments = 0
    created_user = False

    async with session_factory() as session:
        # ------------------------------------------------------------------
        # Seed road segments
        # ------------------------------------------------------------------
        for seg in ROAD_SEGMENTS:
            geom_wkt = seg.pop("geom_wkt")
            stmt = (
                insert(RoadSegment)
                .values(
                    id=seg["id"],
                    pilot="default",
                    name=seg["name"],
                    road_class=seg["road_class"],
                    length_m=seg["length_m"],
                    speed_limit_kmh=seg["speed_limit_kmh"],
                    lanes=seg["lanes"],
                    geom=f"SRID=4326;{geom_wkt}",
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            result = await session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                created_segments += 1
            else:
                skipped_segments += 1
            # Restore for any later reference
            seg["geom_wkt"] = geom_wkt

        # ------------------------------------------------------------------
        # Seed admin user
        # ------------------------------------------------------------------
        from sqlalchemy import select
        existing = await session.execute(
            select(User).where(User.email == DEMO_ADMIN["email"])
        )
        user_row = existing.scalar_one_or_none()
        if user_row is None:
            password_hash = pwd_ctx.hash(DEMO_ADMIN["password"])
            stmt = (
                insert(User)
                .values(
                    email=DEMO_ADMIN["email"],
                    name=DEMO_ADMIN["name"],
                    role=DEMO_ADMIN["role"],
                    pilot_scope=DEMO_ADMIN["pilot"],
                    password_hash=password_hash,
                    is_active=True,
                )
                .on_conflict_do_nothing(index_elements=["email"])
            )
            result = await session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                created_user = True

        await session.commit()

    await engine.dispose()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("  Seed Summary")
    print("=" * 60)
    print(f"  Road segments created : {created_segments}")
    print(f"  Road segments skipped : {skipped_segments} (already existed)")
    print(f"  Admin user created    : {'yes' if created_user else 'no (already existed)'}")
    print()
    print("  Connection info")
    print(f"    DATABASE_URL : {DATABASE_URL}")
    print()
    print("  Demo credentials")
    print(f"    Username / e-mail : {DEMO_ADMIN['email']}")
    print(f"    Password          : {DEMO_ADMIN['password']}")
    print(f"    Role              : {DEMO_ADMIN['role']}")
    print(f"    Pilot scope       : {DEMO_ADMIN['pilot']}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_migrations()
    asyncio.run(seed())
