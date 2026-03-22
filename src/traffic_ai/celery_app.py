"""Celery application configuration."""
from celery import Celery
from traffic_ai.config import settings, get_profile

app = Celery("traffic_ai", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json",
    timezone="UTC", enable_utc=True, task_track_started=True, task_acks_late=True,
    worker_prefetch_multiplier=1, worker_concurrency=settings.celery_concurrency,
    task_default_queue="default",
    task_reject_on_worker_lost=True,
)
app.autodiscover_tasks(["traffic_ai.tasks"])
_profile = get_profile()
app.conf.beat_schedule = {
    # ── Generic / custom loop detectors (from LOOP_DETECTOR_URLS env var)
    "poll-loop-detectors": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_loop_detectors",
        "schedule": 60.0,
    },
    # ── Madrid Ayuntamiento — 4,000+ sensors, data updated every 5 min
    "poll-madrid-loops": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_madrid_loops",
        "schedule": 300.0,  # every 5 minutes to match source update rate
    },
    # ── Barcelona Open Data BCN — traffic state, updated every 5 min
    "poll-barcelona": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_barcelona",
        "schedule": 300.0,
    },
    # ── DGT national incidents (accidents, roadworks, closures)
    "poll-dgt-incidents": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_dgt_incidents",
        "schedule": 180.0,  # every 3 min — DGT refreshes ~every 3 min
    },
    # ── DGT national cameras — round-robin across 1,400+ cameras
    "poll-dgt-cameras": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_dgt_cameras",
        "schedule": float(_profile.risk_compute_interval_s),  # same cadence as risk
    },
    # ── Madrid city cameras — round-robin, 5-min official refresh
    "poll-madrid-cameras": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_madrid_cameras",
        "schedule": 300.0,
    },
    # ── Madrid Informo per-tramo traffic state — updated every 5 min
    "poll-madrid-traffic-state": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_madrid_traffic_state",
        "schedule": 300.0,  # every 5 min — matches Informo update rate
    },
    # ── Valencia city real-time traffic state — updated every 3 min
    "poll-valencia-traffic": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_valencia_traffic",
        "schedule": 180.0,  # every 3 min — matches Valencia update rate
    },
    # ── TomTom national incidents — 1 call/poll, every 5 min (288 calls/day)
    "poll-tomtom-incidents": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_tomtom_incidents",
        "schedule": 300.0,
    },
    # ── TomTom flow — 6 key highway points, every 10 min (864 calls/day)
    "poll-tomtom-flow": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_tomtom_flow",
        "schedule": 600.0,
    },
    # ── Weather
    "poll-weather": {
        "task": "traffic_ai.tasks.weather_tasks.poll_all_weather",
        "schedule": float(_profile.weather_poll_interval_s),
    },
    # ── Risk scoring (uses all the above data)
    "compute-risk-scores": {
        "task": "traffic_ai.tasks.risk_tasks.compute_all_risk_scores",
        "schedule": float(_profile.risk_compute_interval_s),
    },
    # ── Baseline recalculation from InfluxDB history
    "recalculate-baselines": {
        "task": "traffic_ai.tasks.sensor_tasks.recalculate_baselines",
        "schedule": float(_profile.baseline_recalc_interval_s),
    },
}
