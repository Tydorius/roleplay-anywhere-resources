"""Zone arrangements: around_green gives one green ringed by its path with
every building facing it (the largest at the head opposite the road mouth,
no side streets, the centre props on the green itself), fields gathers a
zone's buildings at the road-side corner with crop plots round them, and a
zone too small for its green keeps today's path shape."""
import json
import os
import random
import unittest

import worldgen
from worldgen import layout_zone
from worldgen.model import Rect, SIDE_DX_DY, parse_plan

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "village.json")


def load(arrangements, drop=()):
    """village.json with each named zone given an arrangement; ``drop``
    removes buildings (by name) from the plan and its zones."""
    with open(FIXTURE, "r", encoding="utf-8") as f:
        data = json.load(f)
    for z in data["zones"]:
        if z["name"] in arrangements:
            z["arrangement"] = arrangements[z["name"]]
        if drop:
            z["buildings"] = [b for b in z["buildings"] if b["name"] not in drop]
    if drop:
        data["buildings"] = [b for b in data["buildings"] if b["name"] not in drop]
    return data


def zone_and_templates(data, name):
    plan = parse_plan(data)
    zone = next(z for z in plan.zones if z.name == name)
    return zone, {t.name: t for t in plan.templates}


SOUTH_MOUTH = {(x, 0) for x in range(18, 21)}   # one road mouth on the south edge


def tiny_plan(arrangement, huts=2):
    """A one-zone plan of huts, small enough to test cramped rects with."""
    return {
        "name": "Tiny", "worldBackground": "A test hamlet.", "mapSize": "small",
        "setting": {"era": "iron age", "technology": "wood", "density": "sparse",
                    "climate": "temperate"},
        "zones": [{"name": "Hamlet", "kind": "village", "sizeClass": "small",
                   "description": "huts", "ground": "grass",
                   "arrangement": arrangement,
                   "buildings": [{"name": f"Hut {i + 1}", "kind": "home",
                                  "sizeClass": "hut", "purpose": "sleep"}
                                 for i in range(huts)],
                   "dressing": {"paths": "dirt", "props": [], "filler": []}}],
        "roads": [],
        "templates": [],
        "buildings": [
            {"name": f"Hut {i + 1}", "wall": "wood", "ground": "wood",
             "rooms": [{"name": "Hall", "share": "medium", "purpose": "living"}],
             "connections": [], "entrance": {"room": "Hall", "side": "south"},
             "furniture": []} for i in range(huts)],
        "npcs": [], "player": {"name": "Player"},
    }


class TestAroundGreen(unittest.TestCase):
    def layout(self, w=58, h=50, seed=4):
        zone, templates = zone_and_templates(
            load({"Village Green": "around_green"}), "Village Green")
        return layout_zone.layout_zone(zone, Rect(0, 0, w, h), templates,
                                       random.Random(seed),
                                       road_reserved=SOUTH_MOUTH)

    def test_one_ring_path_and_no_side_streets(self):
        out = self.layout()
        self.assertIsNotNone(out.feature)
        self.assertEqual(out.side_streets, [])
        self.assertTrue(out.street.contains_rect(out.feature))
        self.assertEqual(out.street.w, out.feature.w + 2 * layout_zone.PATH_WIDTH)
        self.assertEqual(out.street.h, out.feature.h + 2 * layout_zone.PATH_WIDTH)

    def test_buildings_face_the_green_from_several_sides(self):
        out = self.layout()
        self.assertEqual(len(out.buildings), 4)
        gcx, gcy = out.feature.center()
        sides = set()
        for b in out.buildings:
            r = b.layout.rect
            cx, cy = r.center()
            dx, dy = SIDE_DX_DY[b.layout.entrance_side]
            self.assertGreater(dx * (gcx - cx) + dy * (gcy - cy), 0,
                               f"{b.layout.design.name} does not face the green")
            self.assertFalse(r.intersects(out.feature),
                             f"{b.layout.design.name} stands on the green")
            sides.add("north" if cy > gcy else "south" if cy < gcy else
                      "east" if cx > gcx else "west")
        self.assertGreaterEqual(len(sides), 2, "all buildings on one side of the green")

    def test_largest_building_at_the_head_opposite_the_road(self):
        out = self.layout()
        inn = next(b for b in out.buildings
                   if b.layout.design.name == "The Green Dragon Inn")
        self.assertGreater(inn.layout.rect.y, out.feature.y1,
                           "the largest building is not north of the green")
        self.assertEqual(inn.layout.entrance_side, "south")

    def test_centre_props_stand_on_the_green(self):
        out = self.layout()
        on_green = [p for p in out.props
                    if p.template in ("Village well", "Market cross")]
        self.assertEqual(len(on_green), 2)
        for p in on_green:
            self.assertTrue(out.feature.contains_cell(p.pos),
                            f"{p.template} is not on the green")

    def test_zone_too_small_for_a_green_keeps_a_street(self):
        zone, templates = zone_and_templates(tiny_plan("around_green"), "Hamlet")
        out = layout_zone.layout_zone(zone, Rect(0, 0, 24, 13), templates,
                                      random.Random(4),
                                      road_reserved={(x, 0) for x in range(11, 14)})
        self.assertIsNone(out.feature)
        self.assertIsNotNone(out.street)
        self.assertEqual(len(out.buildings), 2)
        self.assertEqual([f for f in out.failures if "no space" in f[1]], [])

    def test_full_world_reachable(self):
        world = worldgen.run(load({"Village Green": "around_green"}), seed=1)
        self.assertEqual(world.metrics["reachability"], 1.0)
        self.assertEqual(world.metrics["region_overlaps"], [])
        self.assertTrue(any(r.kind == "square" and r.parent == "Village Green"
                            for r in world.regions))

    def test_the_green_is_named_and_grassed(self):
        world = worldgen.run(load({"Village Green": "around_green"}), seed=1)
        green = next(r for r in world.regions
                     if r.kind == "square" and r.parent == "Village Green")
        self.assertEqual(green.name, "Village Green Green")
        self.assertEqual((green.ground, green.ground_texture), ("grass", "grass"))

    def test_green_name_takes_the_zones_own_feature(self):
        from worldgen.model import Zone, green_feature_name
        self.assertEqual(green_feature_name(
            Zone("Emberwick", outdoor=["the green", "the well"])), "The Green")
        self.assertEqual(green_feature_name(
            Zone("Emberwick", outdoor=["the common"])), "The Common")
        self.assertEqual(green_feature_name(
            Zone("Emberwick", outdoor=["the well"])), "Emberwick Green")
        self.assertEqual(green_feature_name(Zone("Emberwick")), "Emberwick Green")

    def test_the_green_leans_toward_its_only_road_mouth(self):
        # one south mouth in a tall zone: the ring sits a lot's depth off
        # that edge, so the entry arm is short and the slack lies behind
        # the green instead of as a long lone path in front of it
        zone, templates = zone_and_templates(
            load({"Village Green": "around_green"}), "Village Green")
        for seed in (0, 4, 7):
            out = layout_zone.layout_zone(zone, Rect(0, 0, 40, 60), templates,
                                          random.Random(seed),
                                          road_reserved=SOUTH_MOUTH)
            self.assertIsNotNone(out.feature, f"seed {seed}")
            self.assertLess(out.street.y, (60 - out.street.h) / 2.0,
                            f"seed {seed}: the green sits centred, not near its mouth")


class TestFieldsArrangement(unittest.TestCase):
    def layout(self, seed=4):
        zone, templates = zone_and_templates(
            load({"Village Green": "fields"}), "Village Green")
        rect = Rect(0, 0, 54, 44)
        return layout_zone.layout_zone(zone, rect, templates, random.Random(seed),
                                       road_reserved=SOUTH_MOUTH), rect

    def test_buildings_gather_at_the_road_side_corner(self):
        # the mouth is on the south edge at x~19, so the road-side corner is
        # the south-west one: buildings start there and stack away from the
        # lane, the largest inside that quadrant, the cluster collectively
        # nearer to it than to the opposite corner
        for seed in (0, 4):
            out, rect = self.layout(seed)
            self.assertEqual(len(out.buildings), 4, f"seed {seed}")
            near_total = far_total = 0.0
            for b in out.buildings:
                cx, cy = b.layout.rect.center()
                near_total += abs(cx - rect.x) + abs(cy - rect.y)
                far_total += abs(cx - rect.x1) + abs(cy - rect.y1)
                self.assertLess(b.layout.rect.y, rect.y + rect.h / 2.0,
                                f"seed {seed}: {b.layout.design.name} left the road side")
            self.assertLess(near_total, far_total, f"seed {seed}")
            inn = next(b for b in out.buildings
                       if b.layout.design.name == "The Green Dragon Inn")
            icx, icy = inn.layout.rect.center()
            self.assertLess(icx, rect.x + rect.w / 2.0, f"seed {seed}")
            self.assertLess(icy, rect.y + rect.h / 2.0, f"seed {seed}")

    def test_crop_plots_appear_in_a_non_field_zone(self):
        out, _rect = self.layout()
        self.assertGreaterEqual(len(out.fields), 2)

    def test_full_world_reachable(self):
        world = worldgen.run(load({"Village Green": "fields"}), seed=1)
        self.assertEqual(world.metrics["reachability"], 1.0)
        fields = [r for r in world.regions if r.kind == "field"
                  and r.parent == "Village Green"]
        self.assertGreaterEqual(len(fields), 2)


if __name__ == "__main__":
    unittest.main()
