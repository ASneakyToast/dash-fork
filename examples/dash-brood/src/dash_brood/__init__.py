from pathlib import Path

from dash.plugins import Plugin
from dash_brood.routes import routes

plugin = Plugin(
    name="brood",
    version="0.1.0",
    routes=routes,
    static=Path(__file__).parent / "static",
    script="brood.js",
    style="brood.css",
)
