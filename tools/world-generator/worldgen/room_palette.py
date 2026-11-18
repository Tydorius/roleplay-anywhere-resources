"""The role colour palette and the plan label rule of the room library,
shared by the room sheets (library-seed/room_sheet.py) and the Scenario
Editor's Rooms tab so the two cannot drift. No PIL import: the sheets turn
the (r, g, b) tuples into pixels, the editor turns them into "#rrggbb"
strings; rooms.js carries the same short_role rule in JavaScript.
"""

ROLES = (  # specific prefixes first: color() takes the first match
    ("sleep", (196, 106, 84)),
    ("bedside", (222, 158, 138)),
    ("storage", (139, 109, 59)),
    ("wash", (74, 127, 200)),
    ("seat.lounge", (233, 138, 108)),
    ("seat.long", (172, 82, 60)),
    ("seat", (184, 134, 11)),
    ("table.dining", (108, 108, 190)),
    ("table", (163, 117, 61)),
    ("desk", (163, 117, 61)),
    ("counter", (163, 117, 61)),
    ("light", (230, 195, 76)),
    ("hearth", (230, 57, 70)),
    ("heat", (211, 84, 0)),
    ("fuel", (211, 84, 0)),
    ("coat", (120, 144, 156)),
    ("waste", (120, 144, 156)),
    ("decor.feature", (196, 96, 168)),
    ("decor", (156, 127, 176)),
    ("display", (26, 166, 157)),
    ("books", (108, 165, 82)),
)
DEFAULT_ROLE = (158, 158, 158)


def color(role):
    """The (r, g, b) of a role: the first prefix it matches, else the default."""
    for prefix, rgb in ROLES:
        if role == prefix or role.startswith(prefix + "."):
            return rgb
    return DEFAULT_ROLE


def css(role):
    """The role's colour as "#rrggbb" (the editor's side of the palette)."""
    return "#%02x%02x%02x" % color(role)


def short_role(role, roles=None):
    """The label a plan writes on a piece: the role's most telling word.
    The first word by default ("sleep.couple" -> "sleep"), but the last word
    for washroom fixtures ("wash.toilet" -> "toilet": they would all read
    "wash") and wherever the first word alone is ambiguous — another,
    different role in the same room shares it ("storage.big" next to
    "storage.small" -> "big"), so both are told apart by their last word.
    ``roles`` is the room's roles; without it the label cannot disambiguate
    and the first word (the wash rule aside) is all it can promise."""
    words = str(role or "").split(".")
    last = words[-1] if words else ""
    if len(words) > 1 and words[0] == "wash":
        return last
    if roles is not None:
        first = words[0] if words else ""
        for other in set(roles):
            if other != role and str(other or "").split(".")[0] == first:
                return last
    return words[0] if words else ""
