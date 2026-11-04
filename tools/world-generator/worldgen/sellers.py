"""Who sells things. The game stocks anyone flagged as a merchant by itself, so
all the plan has to say is who: an explicit `sells` on the person decides; else
a trade in their role, or being the person who runs a shop or an inn."""
import re

from .schedule import is_inn

# trades that sell what they make; "miller's wife" and an apprentice don't
TRADE_WORD = re.compile(
    r"\b(merchants?|traders?|vendors?|dealers?|peddlers?|pedlars?|"
    r"(?:inn|shop|store|tavern|bar)keep(?:er)?s?|bartenders?|bakers?|butchers?|grocers?|\w+mongers?|chandlers?|"
    r"apothecar(?:y|ies)|pharmacists?|herbalists?|herb-(?:wife|woman)|\w*smiths?|tailors?|"
    r"seamstress(?:es)?|dressmakers?|cobblers?|shoemakers?|coopers?|potters?|weavers?|tanners?|"
    r"saddlers?|fletchers?|bowyers?|armou?rers?|brewers?|vintners?|millers?|florists?|"
    r"jewell?ers?|\w+sellers?)\b(?!['’]s)")
HELPER_WORD = re.compile(r"\bapprentices?\b")
HEAD_WORD = re.compile(r"\b(owner|proprietor|keeper|manager|landlord|landlady)\b")
SHOP_KIND = re.compile(r"\b((?!work)\w*shops?|stores?|stalls?|kiosks?|markets?|bakery|butchery|"
                       r"grocery|pharmacy|apothecary|bodegas?|emporium|boutiques?|diners?|cafes?|"
                       r"cafés?|restaurants?|takeout|takeaway|trading post)\b")
SELL_WORD = re.compile(r"\bsell(s|ing)?\b")


def is_shop(building):
    """Whether customers buy things here: an inn, or a shop by its kind. A
    "store" is a shop too, and costs nothing if it's really a storehouse."""
    design = building.layout.design
    return (is_inn(building) or bool(SHOP_KIND.search((design.kind or "").lower()))
            or bool(SELL_WORD.search((design.purpose or "").lower())))


def _stated(person):
    """The plan's own word on it, or None to leave it to the rule."""
    sells = person.extras.get("sells")
    return sells if isinstance(sells, bool) else None


def _has_trade(person):
    role = (person.role or "").lower()
    return bool(TRADE_WORD.search(role)) and not HELPER_WORD.search(role)


def _rank(person):
    """Who stands behind the counter: the head, then staff, then apprentices."""
    role = (person.role or "").lower()
    return 0 if HEAD_WORD.search(role) else 2 if HELPER_WORD.search(role) else 1


def sellers(world):
    """The names of everyone who sells. Each working shop has at least one, so
    an owner-cook or a clerk can trade without a word for it in their role."""
    people = [c.person for c in world.characters if not c.is_player]
    out = {p.name for p in people
           if _stated(p) or (_stated(p) is None and _has_trade(p))}
    for building in world.buildings:
        if not is_shop(building):
            continue
        staff = [p for p in people if p.work == building.layout.design.name]
        if any(p.name in out for p in staff):
            continue
        free = [p for p in staff if _stated(p) is None]
        if free:
            out.add(min(free, key=_rank).name)
    return out
