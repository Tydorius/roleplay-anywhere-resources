"""The lights extension: each light source gets a kind and, now and then, a colour.

The plain game lights every template whose ``light`` is above 0 with the same
orange lamp. The ``lights`` game mod
(``roleplay-anywhere-resources/tools/code-mod-loader/examples/lights``) gives
each one a kind instead: candles flicker small and warm, hearths throw
embers, bulbs hold steady, neon stutters, arcane crystals pulse blue. The mod
classifies light sources by name and description on its own; this extension
asks the catalogue phase to say the kind outright (``lightKind``) and to give
a ``lightColor`` where the setting calls for an unusual one, and writes them
as ``arpgMods.lights.templates`` keyed by template name.

A template with a kind but no ``light`` strength gets its kind's usual one,
so it is lit at all: the game makes lights only for ``light`` above 0.
"""
import re

# The mod's kinds ("plain" is the game's own look, so the model is never offered it).
KINDS = ("candle", "torch", "fire", "ember", "lantern", "electric", "neon", "screen", "magic")

# A kind's usual strength (0..1), in line with the game's own scenarios: a
# candle stand 0.2, a lamppost 0.6 to 0.8, a hearth 0.8, a campfire 1.0.
KIND_LIGHT = {"candle": 0.2, "torch": 0.6, "fire": 0.8, "ember": 0.3, "lantern": 0.5,
              "electric": 0.6, "neon": 0.5, "screen": 0.3, "magic": 0.4}

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def light_for(template):
    """The ``light`` strength the spec should carry for ``template`` with this
    extension on: the catalogue's own value, else its kind's usual one."""
    v = template.extras.get("light")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return v
    return KIND_LIGHT.get(template.extras.get("lightKind"))


def arpg_mods(world):
    """The spec's arpgMods part: ``{"lights": {"templates": {name: kind or
    {kind, color}}}}`` for every lit template with a kind, or {} when the
    catalogue named none (the mod still classifies them by name)."""
    entries = {}
    for t in world.templates.values():
        kind = t.extras.get("lightKind")
        if kind not in KINDS or not light_for(t):
            continue
        color = t.extras.get("lightColor")
        entries[t.name] = {"kind": kind, "color": color.lower()} if color else kind
    return {"lights": {"templates": entries}} if entries else {}
