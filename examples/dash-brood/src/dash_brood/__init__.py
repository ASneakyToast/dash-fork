from pathlib import Path

from dash.plugins import Plugin
from dash.theme import Theme, Token
from dash_brood.routes import routes

HERE = Path(__file__).parent

TOKENS = (
    Token("brood.water.top", "#4aa6d6", "#134069", description="The water at the surface."),
    Token("brood.water.mid", "#2c78a8", "#0a1f3d", description="The water at mid depth."),
    Token("brood.water.deep", "#16486e", "#040a16", description="The water at the bottom."),
    Token("brood.floor", "#173a5a", "#0b1423", description="The sea floor."),
    Token("brood.weed", "#1f8a7a", "#134a47", description="The weeds on the sea floor."),
    Token("brood.light", "#e3f6ff", "#aae1ff", description="Light shafts and bubbles."),
    Token("brood.egg.shell", "#fff7fb", description="A waiting job's egg, lit side."),
    Token("brood.egg.shade", "#d9a8c9", description="A waiting job's egg, shaded side."),
    Token("brood.pearl", "#fff4c8", description="A pearl, which is a new memory."),
    Token("brood.ink", "#0d0a1a", description="Pupils and outlines."),
    Token("brood.sclera", "#ffffff", description="The whites of the eyes."),
    Token("brood.label.bg", "rgba(0, 0, 0, 0.7)", description="The hover label background."),
    Token("brood.label.text", "#ffffff", description="The hover label text."),
    Token("brood.sleep", "#dce6ff", description="The z's of a sleeping mother."),
    Token("brood.bezel", "#2a3140", "#0e1118", description="The phone frame."),
    Token("brood.bezel.edge", "#c4cbda", "#2b3140", description="The rim of the phone frame."),
    Token("brood.mood.content", "hsl(268 58% 64%)", description="The mother when all is well."),
    Token("brood.mood.busy", "hsl(188 72% 62%)", description="The mother when jobs are running."),
    Token("brood.mood.strained", "hsl(24 82% 62%)", description="The mother with a long queue."),
    Token("brood.mood.sick", "hsl(96 30% 54%)", description="The mother when jobs are failing."),
    Token("brood.mood.asleep", "hsl(250 26% 40%)", description="The mother with no worker."),
)

plugin = Plugin(
    name="brood",
    version="0.2.0",
    routes=routes,
    static=HERE / "static",
    script="brood.js",
    style="brood.css",
    tokens=TOKENS,
    themes=[Theme.load(HERE / "tidepool.json")],
)
