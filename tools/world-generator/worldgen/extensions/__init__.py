"""Mod extensions a run may enable.

Every extension is an opt-in toggle, **off by default**: a run without
extensions needs no game mods — the base prompts never mention a mod
feature, and the built zip imports and plays in the unmodded game. The
registry below is what a UI lists as unchecked toggles.

An extension adds prompt fragments (``worldgen/prompts/ext/<ext>/<phase>.txt``,
appended to that phase's prompt when enabled), contract fields for the model
to reply with, and — for floors — a post-layout step that places the extra
storeys and writes the game-mod data (``arpgMods``). A run without an
extension never mentions its features to the model and never runs its code.

The game mods live in ``roleplay-anywhere-resources/tools/code-mod-loader``
(``portals``, ``floors``, ``region-groups``, ``lights``); an extension's ``mods``
names the ones it needs.

``floors`` needs ``portals`` (its stairs are portal pads): enabling floors
turns portals on too — :func:`expand` records that, and :func:`expand_notes`
says so for a user.
"""


class Extension:
    """One labelled toggle. ``default`` is False for every extension: the
    plain path must need no mods."""

    def __init__(self, id, title, mods, description, requires=(), without_mod=None):
        self.id = id
        self.title = title
        self.mods = tuple(mods)            # game mods needed (code-mod-loader names)
        self.description = description
        self.requires = tuple(requires)    # extensions turned on with it
        self.without_mod = without_mod     # what a world built with it is like without its mods
        self.default = False

    def as_dict(self):
        return {"id": self.id, "title": self.title, "mods": list(self.mods),
                "description": self.description, "requires": list(self.requires),
                "withoutMod": self.without_mod or "the world won't work right without "
                              + ("them" if len(self.mods) > 1 else "it"),
                "default": self.default}


REGISTRY = (
    Extension("floors", "Floors (upper storeys)", ("portals", "floors"),
              "Multi-storey buildings: bedrooms and halls upstairs, reached by "
              "stair portals, in a lit band beyond the world's dark edge.",
              requires=("portals",)),
    Extension("portals", "Portals", ("portals",),
              "Two-way portal pads linking two cells; the stairs between "
              "storeys are portals."),
    Extension("region-groups", "Region groups", ("region-groups",),
              "A zone may wrap around the map and still act as one region; "
              "wilder zone shapes for large plans."),
    Extension("lights", "Lights (kinds and colours)", ("lights",),
              "Each light source gets a kind (candle, hearth fire, lantern, "
              "electric, neon, screen, magic) and, where the setting calls "
              "for it, a colour: flicker, embers and coloured glow in game.",
              without_mod="without it the world still plays; its lamps just look plain"),
)

BY_ID = {e.id: e for e in REGISTRY}
IDS = tuple(e.id for e in REGISTRY)
IMPLIED = {e.id: e.requires for e in REGISTRY if e.requires}


def expand(exts):
    """The full extension set implied by ``exts`` (floors implies portals)."""
    out = set()
    for e in exts or ():
        out.add(e)
        out.update(IMPLIED.get(e, ()))
    return out


def expand_notes(exts):
    """(full extension set, one note per dependency the user did not name
    directly) — turning floors on turns portals on, and says so."""
    given = set(exts or ())
    full = expand(given)
    notes = []
    for e in REGISTRY:
        implied = set(e.requires) & full - given
        if e.id in given and implied:
            notes.append(f"{e.id} also enables {', '.join(sorted(implied))} "
                         f"(the {e.id} extension needs the "
                         f"{', '.join(e.mods)} game mod(s) installed)")
    return full, notes


def registry():
    """The extensions as plain dicts, for a UI's toggle list."""
    return [e.as_dict() for e in REGISTRY]
