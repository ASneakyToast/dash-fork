from collections.abc import Mapping, Sequence

from dash.queue import Activity

SICK_WINDOW_SECONDS = 600
STRAINED_WAITING = 3


def mood(status: Mapping[str, int], recent: Sequence[Activity], now: float) -> str:
    """Return how the mother feels given the queue status and the recent activity."""
    failures = sum(1 for a in recent if a.kind == "failed" and now - a.at < SICK_WINDOW_SECONDS)
    if status["workers"] == 0:
        return "asleep"
    if failures:
        return "sick"
    if status["waiting"] >= STRAINED_WAITING:
        return "strained"
    if status["in_flight"]:
        return "busy"
    return "content"
