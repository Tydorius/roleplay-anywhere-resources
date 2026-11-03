"""Placement-hint parsing (DESIGN.md "Placement hints" table).

Hints are short strings shared by every level; several combine with ``+``
(for example ``wall:north+center``). Unknown hints mean "anywhere free":
the parse succeeds but no constraint flags are set.
"""
from dataclasses import dataclass, field

SIDES = ("north", "south", "east", "west")


@dataclass
class Hint:
    raw: str
    walls: tuple = ()            # sides from wall:<side>
    row: str = None              # side from row:<side>
    corner: bool = False
    center: bool = False
    beside: str = None           # template name from beside:<template>
    around: str = None           # template name from around:<template>
    near_door: bool = False
    away_from_door: bool = False
    symmetric: bool = False
    building_ref: str = None     # building name from behind:/front:/beside:<building>
    rel: str = None              # behind | front | beside
    along_path: bool = False
    edge: bool = False
    cluster: bool = False
    scatter: bool = False
    unknown: tuple = ()

    @property
    def constrained(self):
        """False when the hint carries no usable constraint (anywhere free)."""
        return bool(self.walls or self.row or self.corner or self.center or self.beside
                    or self.around or self.near_door or self.away_from_door or self.symmetric
                    or self.building_ref or self.along_path or self.edge
                    or self.cluster or self.scatter)


def parse(text):
    """Parse a hint string; never raises. Unknown tokens land in .unknown."""
    h = Hint(raw=text or "")
    for token in (text or "").split("+"):
        token = token.strip()
        if not token:
            continue
        key, _, value = token.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "wall":
            if value in SIDES:
                h.walls = h.walls + (value,)
            elif value == "any":
                pass
            else:
                h.unknown = h.unknown + (token,)
        elif key == "row" and value in SIDES:
            h.row = value
        elif key == "beside" and value:
            h.beside = value
        elif key == "around" and value:
            h.around = value
        elif key in ("behind", "front") and value:
            h.building_ref = value
            h.rel = key
        elif token == "corner":
            h.corner = True
        elif token == "center":
            h.center = True
        elif token == "near_door":
            h.near_door = True
        elif token == "away_from_door":
            h.away_from_door = True
        elif token == "symmetric":
            h.symmetric = True
        elif token == "along_path":
            h.along_path = True
        elif token == "edge":
            h.edge = True
        elif token == "cluster":
            h.cluster = True
        elif token == "scatter":
            h.scatter = True
        else:
            h.unknown = h.unknown + (token,)
    return h
