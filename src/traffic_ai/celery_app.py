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
    "poll-loop-detectors": {
        "task": "traffic_ai.tasks.sensor_tasks.poll_loop_detectors",
        "schedule": 60.0,
    },
    "poll-weather": {
        "task": "traffic_ai.tasks.weather_tasks.poll_all_weather",
        "schedule": float(_profile.weather_poll_interval_s),
    },
    "compute-risk-scores": {
        "task": "traffic_ai.tasks.risk_tasks.compute_all_risk_scores",
        "schedule": float(_profile.risk_compute_interval_s),
    },
    "recalculate-baselines": {
        "task": "traffic_ai.tasks.sensor_tasks.recalculate_baselines",
        "schedule": float(_profile.baseline_recalc_interval_s),
    },
}
