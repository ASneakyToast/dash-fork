import time
from typing import Any

from fastapi.routing import APIRouter

from dash.plugins import Context
from dash_brood.mood import mood

RECENT = 50


def routes(ctx: Context) -> APIRouter:
    """Return the routes that tell the browser how the mother feels."""
    router = APIRouter()

    @router.get("/mother")
    async def mother() -> dict[str, Any]:
        status = await ctx.queue.status()
        now = time.time()
        return {
            **status,
            "mood": mood(status, await ctx.queue.recent_activity(RECENT), now),
            "now": now,
        }

    return router
