"""Content-free projection over existing scheduler and Action Center truth."""

from .action_center import ActionCenter

QUEUE_FIELDS = frozenset({"queued", "running", "paused", "attention", "complete"})


def queue_state(value):
    if value is None or not normalize_queue(value)["complete"]:
        return "degraded"
    for key in ("attention", "running", "queued", "paused"):
        if value[key] > 0:
            return key
    return "idle"


def normalize_queue(value):
    if (
        not isinstance(value, dict)
        or set(value) != QUEUE_FIELDS
        or type(value["complete"]) is not bool
    ):
        raise ValueError("invalid tray queue observation")
    for key in QUEUE_FIELDS - {"complete"}:
        if value[key] is None and key == "attention" and not value["complete"]:
            continue
        if type(value[key]) is not int or not 0 <= value[key] <= (1 << 53) - 1:
            raise ValueError("invalid tray queue count")
    return dict(value)


def queue_snapshot(instance):
    scheduler = instance.scheduler_status()["job_states"]
    attention = ActionCenter(instance.store).snapshot(limit=1)
    return normalize_queue(
        {
            "queued": sum(scheduler.get(key, 0) for key in ("queued", "retry_wait")),
            "running": sum(scheduler.get(key, 0) for key in ("running", "pausing", "cancelling")),
            "paused": scheduler.get("paused", 0),
            "attention": attention["total"] if attention["complete"] else None,
            "complete": attention["complete"],
        }
    )
