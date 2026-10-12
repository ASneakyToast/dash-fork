import asyncio
import logging
import signal

import click
import uvicorn

from dash.config import Settings


@click.group()
def main() -> None:
    """dash: always-on assistant in front of hermes-agent."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@main.command()
def migrate() -> None:
    """Upgrade the database schema to head. Needs DATABASE_URL."""
    from dash.db import migrate as run

    run(Settings.from_env().database_url)


@main.command()
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Address to bind. Use 0.0.0.0 only inside a container.",
)
@click.option("--port", default=8000, show_default=True, help="Port to bind.")
def serve(*, host: str, port: int) -> None:
    """Run the web UI and API."""
    uvicorn.run("dash.web:create_production_app", factory=True, host=host, port=port)


@main.command()
def worker() -> None:
    """Consume the job queue and answer through hermes."""
    asyncio.run(_worker())


async def _worker() -> None:
    from dash.db import Store
    from dash.hermes import Hermes
    from dash.memory import memory_models
    from dash.queue import Queue
    from dash.worker import Worker

    settings = Settings.from_env()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    memory = memory_models(settings)
    hermes = Hermes(settings.hermes_base_url, settings.hermes_api_key, settings.hermes_model)
    queue = Queue.from_url(settings.redis_url)
    async with Store.connect(settings.database_url) as store:
        try:
            await Worker(
                store=store,
                queue=queue,
                chat=hermes,
                embedder=memory,
                extractor=memory,
                top_k=settings.memory_top_k,
            ).run(stop)
        finally:
            await hermes.close()
            await memory.close()
            await queue.close()
