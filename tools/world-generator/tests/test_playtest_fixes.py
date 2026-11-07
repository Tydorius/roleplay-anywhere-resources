"""What the first full play of a generated world found: Downpour Block played
through a whole day on 2026-11-04. Stall-holders roamed their whole market,
children spent the day in the bedroom, people left for work as their shift began
and got there late, a new player could afford nothing, and the portraits needed
their age spelled out."""
import types
import unittest

from worldgen import RegionOut, phases, schedule, spec_writer
from worldgen.model import Rect


def template(tags=("work",), size=(2, 2), for_sleep=False, capacity=None):
    return types.SimpleNamespace(tags=list(tags), size=size, for_sleep=for_sleep)


def world_with(zone_rect, regions=(), objects=(), templates=None):
    zone = RegionOut("Market", zone_rect, "zone", ground="stone", ground_texture="rock")
    all_regions = [zone] + list(regions)
    return types.SimpleNamespace(
        regions=all_regions, regions_by_name={r.name: r for r in all_regions},
        objects=list(objects), templates=templates or {},
        zones_by_name={"Market": zone}, buildings=[])


def obj(template_name, pos):
    return types.SimpleNamespace(template=template_name, pos=pos, region="Market")


class TestPosts(unittest.TestCase):
    TEMPLATES = {"Stall": template(("work", "landmark")), "Puddle": template(("water", "filler")),
                 "Planter": template(("plant",), (1, 1))}

    def world(self, objects, regions=()):
        return world_with(Rect(0, 0, 40, 30), regions, objects, self.TEMPLATES)

    def post(self, world, name):
        return world.regions_by_name[name].rect

    def test_a_post_holds_its_stall_and_little_else(self):
        w = self.world([obj("Stall", (20, 15))])
        (name,) = schedule.make_posts(w, "Market", 2)
        rect = self.post(w, name)
        self.assertTrue(rect.contains_cell((20, 15)) and rect.contains_cell((21, 16)))
        self.assertLessEqual(rect.w, 2 + 2 * schedule.POST_REACH)
        self.assertLessEqual(rect.h, 2 + 2 * schedule.POST_REACH)

    def test_a_stall_against_the_edge_still_gets_a_post(self):
        """Downpour's three carts sat in a strip two cells deep, between the
        zone's edge and a row of shops."""
        shops = RegionOut("Shops", Rect(0, 2, 40, 20), "compound")
        w = self.world([obj("Stall", (20, 0))], [shops])
        (name,) = schedule.make_posts(w, "Market", 2)
        self.assertEqual(self.post(w, name).h, 2)

    def test_stalls_side_by_side_keep_separate_posts(self):
        w = self.world([obj("Stall", (10, 5)), obj("Stall", (12, 5)), obj("Stall", (14, 5))])
        names = schedule.make_posts(w, "Market", 6)
        rects = [self.post(w, n) for n in names]
        self.assertGreaterEqual(len(rects), 2)
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertFalse(a.intersects(b), (a, b))

    def test_a_post_never_cuts_a_building(self):
        shop = RegionOut("Shop", Rect(23, 14, 6, 6), "building", wall="wood")
        w = self.world([obj("Stall", (20, 15))], [shop])
        (name,) = schedule.make_posts(w, "Market", 2)
        self.assertFalse(self.post(w, name).intersects(shop.rect))

    def test_work_objects_come_first_and_filler_never(self):
        w = self.world([obj("Puddle", (5, 5)), obj("Planter", (8, 8)), obj("Stall", (30, 20))])
        names = schedule.make_posts(w, "Market", 4)
        self.assertEqual(names[0], "Market Stall Post")
        self.assertFalse(any("Puddle" in n for n in names))

    def test_a_post_nobody_can_reach_is_skipped(self):
        w = self.world([obj("Stall", (20, 15))])
        self.assertEqual(schedule.make_posts(w, "Market", 2, connected={(1, 1)}), [])

    def test_only_enough_posts_for_the_people(self):
        w = self.world([obj("Stall", (5, 5)), obj("Stall", (15, 5)), obj("Stall", (25, 5))])
        self.assertEqual(len(schedule.make_posts(w, "Market", 2)), 1)

    def test_workers_fill_a_post_then_the_next(self):
        w = self.world([obj("Stall", (5, 5)), obj("Stall", (25, 5))])
        posts = {"Market": schedule.make_posts(w, "Market", 4)}
        load = schedule._Load(w)
        hours = list(range(6, 18))
        person = types.SimpleNamespace(work="Market", home="Home", name="A")
        placed = []
        for _ in range(4):
            place = schedule._place_work(w, load, person, hours, "Bed", posts)
            load.add(place, hours)
            placed.append(place)
        self.assertEqual(sorted(placed), sorted(posts["Market"] * 2))

    def test_no_stall_leaves_the_zone_itself(self):
        w = self.world([])
        self.assertEqual(schedule.make_posts(w, "Market", 2), [])
        person = types.SimpleNamespace(work="Market", home="Home", name="A")
        self.assertEqual(schedule._place_work(w, schedule._Load(w), person, [8], "Bed", {}),
                         "Market")


class TestLeavingForWork(unittest.TestCase):
    def world(self, gap):
        home = RegionOut("Home", Rect(0, 0, 5, 5), "room")
        work = RegionOut("Work", Rect(gap, 0, 5, 5), "room")
        return types.SimpleNamespace(regions_by_name={"Home": home, "Work": work})

    def day(self):
        return [(("06:00", "18:00"), "Work", "work"), (("18:00", "22:00"), "Home", "leisure"),
                (("22:00", "06:00"), "Home", "sleep")]

    def test_a_long_walk_starts_early_and_the_night_gives_way(self):
        blocks = schedule._leave_early(self.world(150), self.day())
        self.assertEqual(blocks[0][0], ("05:15", "18:00"))
        self.assertEqual(blocks[2][0], ("22:00", "05:15"))

    def test_a_short_walk_changes_nothing(self):
        self.assertEqual(schedule._leave_early(self.world(30), self.day()), self.day())

    def test_a_night_shift_leaves_before_ten(self):
        night = [(("06:00", "08:00"), "Home", "leisure"), (("08:00", "16:00"), "Home", "sleep"),
                 (("16:00", "22:00"), "Home", "leisure"), (("22:00", "06:00"), "Work", "work")]
        blocks = schedule._leave_early(self.world(150), night)
        self.assertEqual(blocks[3][0], ("21:15", "06:00"))
        self.assertEqual(blocks[2][0], ("16:00", "21:15"))

    def test_the_blocks_still_join_up(self):
        blocks = schedule._leave_early(self.world(150), self.day())
        ends = {b[0][1] for b in blocks}
        self.assertEqual({b[0][0] for b in blocks}, ends)

    def test_the_walk_has_a_limit(self):
        self.assertEqual(schedule._commute_minutes(self.world(5000), "Home", "Work"),
                         schedule.MAX_COMMUTE_MINUTES)

    def test_nobody_at_work_is_left_alone(self):
        home = [(("06:00", "22:00"), "Home", "leisure"), (("22:00", "06:00"), "Home", "sleep")]
        self.assertEqual(schedule._leave_early(self.world(150), home), home)


class TestDaysAtHome(unittest.TestCase):
    def room(self, name, beds=0):
        return types.SimpleNamespace(
            base_name=name, full_name=f"Flat 1 {name}",
            furniture=types.SimpleNamespace(placements=[("Bed", (0, 0))] * beds))

    def world(self, rooms):
        flat = types.SimpleNamespace(name="Flat 1", layout=types.SimpleNamespace(rooms=rooms))
        layout = types.SimpleNamespace(design=types.SimpleNamespace(name="Tower"),
                                       unit_outs=[flat])
        tower = types.SimpleNamespace(layout=layout, floors=[])
        bed = types.SimpleNamespace(for_sleep=True, size=(1, 2))
        return types.SimpleNamespace(buildings=[tower], templates={"Bed": bed})

    def test_a_flat_is_lived_in_from_its_main_room(self):
        w = self.world([self.room("Sleeping Room", 3), self.room("Main Room")])
        person = types.SimpleNamespace(home="Tower", name="A")
        self.assertEqual(schedule._home_spot(w, person, "Flat 1 Sleeping Room"),
                         "Flat 1 Main Room")

    def test_a_bedsit_has_only_its_bedroom(self):
        w = self.world([self.room("Sleeping Room", 3)])
        person = types.SimpleNamespace(home="Tower", name="A")
        self.assertEqual(schedule._home_spot(w, person, "Flat 1 Sleeping Room"),
                         "Flat 1 Sleeping Room")

    def test_a_corridor_is_no_living_room(self):
        w = self.world([self.room("Sleeping Room", 3), self.room("Corridor")])
        person = types.SimpleNamespace(home="Tower", name="A")
        self.assertEqual(schedule._home_spot(w, person, "Flat 1 Sleeping Room"),
                         "Flat 1 Sleeping Room")


class TestPortraits(unittest.TestCase):
    def person(self, kind, gender="female"):
        extras = {"kind": kind} if kind else {}
        return types.SimpleNamespace(
            name="A", gender=gender,
            person=types.SimpleNamespace(physicalDescription="A patched raincoat.",
                                         extras=extras, role="noodle cook"))

    def test_a_child_says_so_first(self):
        text = spec_writer.physical_for(self.person("child"))
        self.assertTrue(text.startswith("A young child"))
        self.assertTrue(text.endswith("A patched raincoat."))

    def test_an_elder_says_so_with_their_gender(self):
        self.assertTrue(spec_writer.physical_for(self.person("elder")).startswith("Very old woman"))
        self.assertTrue(spec_writer.physical_for(self.person("elder", "male"))
                        .startswith("Very old man"))

    def test_an_adult_is_left_alone(self):
        self.assertEqual(spec_writer.physical_for(self.person(None)), "A patched raincoat.")


class TestMoney(unittest.TestCase):
    def test_a_small_purse_is_topped_up(self):
        self.assertEqual(phases.sanitize_p6a({"startingCurrency": 10}, [])["startingCurrency"],
                         phases.MIN_PURSE)

    def test_a_good_purse_stands(self):
        self.assertEqual(phases.sanitize_p6a({"startingCurrency": 400}, [])["startingCurrency"], 400)

    def test_no_purse_gets_the_least(self):
        self.assertEqual(phases.sanitize_p6a({}, [])["startingCurrency"], phases.MIN_PURSE)


class TestCatalogue(unittest.TestCase):
    TEMPLATES = [{"name": "Shelf", "size": [1, 1], "walkability": 0, "tags": ["storage"],
                  "description": "A shelf.", "physicalDescription": "a shelf",
                  "rule": "place anywhere free"}]
    ITEM = {"name": "Soup", "type": "consumable", "quality": "common", "value": 3,
            "description": "Soup.", "physicalDescription": "soup, white background"}

    def test_items_without_pools_go_back(self):
        errors = phases.check_p2({"templates": self.TEMPLATES, "items": [self.ITEM]})
        self.assertTrue(any("lootPools" in e for e in errors), errors)

    def test_no_items_needs_no_pools(self):
        errors = phases.check_p2({"templates": self.TEMPLATES})
        self.assertFalse(any("lootPools" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
