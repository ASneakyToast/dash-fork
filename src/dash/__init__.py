import asyncio
import logging
import signal

import click
import uvicorn

from dash.config import Settings


@click.group()
def main() -> None:
    """dash: always-on assistant in front of hermes and other ACP agents."""
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
    """Consume the job queue and answer through each conversation's agent."""
    asyncio.run(_worker())


@main.command()
def agents() -> None:
    """Print the configured agents. Checks DASH_AGENTS without starting any."""
    from dash.agents import Catalog

    settings = Settings.from_env()
    catalog = Catalog.parse(settings.agents, settings.default_agent)
    for spec in catalog.specs:
        mark = "*" if spec.name == catalog.default else " "
        where = " ".join(spec.command) or spec.url or spec.base_url or settings.hermes_base_url
        click.echo(f"{mark} {spec.name}\t{spec.kind}\t{where}")


async def _worker() -> None:
    from dash.agents import Agents, AgentSpec, Catalog, build
    from dash.db import Store
    from dash.hermes import Hermes
    from dash.memory import memory_models
    from dash.plugins import discover
    from dash.queue import Queue
    from dash.worker import Worker

    settings = Settings.from_env()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    def chat(spec: AgentSpec) -> Hermes:
        return Hermes(
            spec.base_url or settings.hermes_base_url,
            spec.api_key or settings.hermes_api_key,
            spec.model or settings.hermes_model,
        )

    catalog = Catalog.parse(settings.agents, settings.default_agent)
    agents = Agents([build(spec, chat=chat) for spec in catalog.specs], catalog.default)
    memory = memory_models(settings)
    queue = Queue.from_url(settings.redis_url)
    async with Store.connect(settings.database_url) as store:
        try:
            worker = Worker(
                store=store,
                queue=queue,
                agents=agents,
                embedder=memory,
                extractor=memory,
                top_k=settings.memory_top_k,
                plugins=discover(settings.plugins, settings.plugins_disabled),
                concurrency=settings.worker_concurrency,
            )
            async with worker.plugins.lifespan(worker.ctx):
                await worker.run(stop)
        finally:
            await agents.close()
            await memory.close()
            await queue.close()
