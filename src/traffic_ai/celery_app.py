"""Celery application configuration."""
from celery import Celery
from traffic_ai.config import settings, get_profile

app = Celery(
    "traffic_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "traffic_ai.tasks.sensor_tasks",
        "traffic_ai.tasks.risk_tasks",
        "traffic_ai.tasks.weather_tasks",
        "traffic_ai.tasks.camera_tasks",
    ],
)
app.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json",
    timezone="UTC", enable_utc=True, task_track_started=True, task_acks_late=True,
    worker_prefetch_multiplier=1, worker_concurrency=settings.celery_concurrency,
    worker_max_tasks_per_child=50,  # restart worker process after 50 tasks to release leaked memory
    task_default_queue="default",
    task_reject_on_worker_lost=True,
    # Limit queue depth — cameras fire every 30s; cap backlog at 8 camera tasks
    # so state/incident tasks are not buried under hundreds of queued camera jobs.
    task_queue_max_priority=10,
    task_default_priority=5,
)
_profile = get_profile()
app.conf.beat_schedule = {
    # ── Barcelona Open Data BCN — traffic state, updated every 5 min
    "poll-barcelona": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_barcelona",
        "schedule": 300.0,
        "options": {"priority": 7},
    },
    # ── DGT national incidents (accidents, roadworks, closures)
    "poll-dgt-incidents": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_dgt_incidents",
        "schedule": 300.0,  # every 5 min — sufficient for incident updates
        "options": {"priority": 6},
    },
    # ── DGT national cameras — Redis-locked, back-to-back batches of 400
    # Beat fires every 45s (was 30s); Redis lock prevents overlapping runs.
    # At ~2s/batch → all 1,916 cameras cycled every ~4.5 min.
    # Slowed slightly from 30s to give state/incident tasks room to run.
    "poll-dgt-cameras": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_dgt_cameras",
        "schedule": 45.0,
        "options": {"priority": 3},  # lower priority than state tasks
    },
    # ── Madrid city cameras — round-robin, 5-min official refresh
    "poll-madrid-cameras": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_madrid_cameras",
        "schedule": 300.0,
        "options": {"priority": 3},
    },
    # ── Madrid Informo per-tramo traffic state — updated every 5 min
    "poll-madrid-traffic-state": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_madrid_traffic_state",
        "schedule": 300.0,
        "options": {"priority": 7},  # high priority — official state data
    },
    # ── Valencia city real-time traffic state — updated every 3 min
    "poll-valencia-traffic": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_valencia_traffic",
        "schedule": 180.0,
        "options": {"priority": 7},
    },
    # ── TomTom national incidents — 1 call/poll, every 5 min (288 calls/day)
    "poll-tomtom-incidents": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_tomtom_incidents",
        "schedule": 300.0,
        "options": {"priority": 6},
    },
    # ── TomTom flow — 6 key highway points, every 10 min (864 calls/day)
    "poll-tomtom-flow": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_tomtom_flow",
        "schedule": 600.0,
        "options": {"priority": 6},
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
    # ── Baseline recalculation — disabled until loop detector data exists
    # Iterates 2.7M segments × InfluxDB queries — prohibitively slow with no data.
    # Re-enable once loop_detector measurements appear in InfluxDB.
    # "recalculate-baselines": {
    #     "task": "traffic_ai.tasks.sensor_tasks.recalculate_baselines",
    #     "schedule": float(_profile.baseline_recalc_interval_s),
    # },
}
