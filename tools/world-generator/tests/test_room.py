import random
import unittest

from worldgen.layout_room import layout_room, reserve_walkways
from worldgen.model import FurniturePlan, ObjectTemplate, Rect


def templates():
    return {
        "Bed": ObjectTemplate(name="Bed", size=(1, 2), tags=["bed"], extras={"forSleep": True}),
        "Table": ObjectTemplate(name="Table", size=(2, 1), tags=["table"]),
        "Stool": ObjectTemplate(name="Stool", size=(1, 1), tags=["chair"]),
        "Chest": ObjectTemplate(name="Chest", size=(2, 2), tags=["storage"]),
    }


def footprint(pos, size):
    return {(x, y) for x in range(pos[0], pos[0] + size[0])
            for y in range(pos[1], pos[1] + size[1])}


class TestRoomLayout(unittest.TestCase):
    def layout(self, w, h, doors, furniture):
        rect = Rect(5, 5, w, h)
        return rect, layout_room(rect, doors, furniture, templates(), random.Random(4))

    def test_no_piece_blocks_a_door_or_walkway(self):
        # doors on north and south walls, so the walkway runs the room's height
        rect = Rect(5, 5, 11, 9)
        door_s = (5 + (11 - 1) // 2, 5)          # (10, 5)
        door_n = (5 + (11 - 1) // 2, 5 + 9 - 1)  # (10, 13)
        door_e = (5 + 11 - 1, 5 + (9 - 1) // 2)  # (15, 8)
        furniture = [
            FurniturePlan("Bed", "R", 3, "wall:north"),
            FurniturePlan("Table", "R", 2, "center"),
            FurniturePlan("Stool", "R", 6, "around:Table"),
            FurniturePlan("Chest", "R", 2, "corner"),
        ]
        out = layout_room(rect, [door_s, door_n, door_e], furniture, templates(), random.Random(7))
        reserved, inner = reserve_walkways(rect, [door_s, door_n, door_e])
        self.assertEqual(reserved, out.reserved)
        for (name, pos) in out.placements:
            size = templates()[name].size
            cells = footprint(pos, size)
            self.assertFalse(cells & out.reserved, f"{name} at {pos} blocks a door/walkway")
            self.assertTrue(rect.interior().contains_rect(
                Rect(pos[0], pos[1], size[0], size[1])), f"{name} at {pos} outside the room interior")

    def test_pieces_do_not_overlap(self):
        _rect, out = self.layout(11, 9, [(10, 5), (10, 13)],
                                 [FurniturePlan("Chest", "R", 6, "corner"),
                                  FurniturePlan("Bed", "R", 4, "wall:west")])
        seen = set()
        for (name, pos) in out.placements:
            size = templates()[name].size
            fp = footprint(pos, size)
            self.assertFalse(fp & seen, f"{name} at {pos} overlaps another piece")
            seen |= fp

    def test_around_places_ring(self):
        rect = Rect(0, 0, 12, 9)
        furniture = [FurniturePlan("Table", "R", 1, "center"),
                     FurniturePlan("Stool", "R", 6, "around:Table")]
        out = layout_room(rect, [(5, 0), (6, 8)], furniture, templates(), random.Random(1))
        table = next(p for (n, p) in out.placements if n == "Table")
        stools = [p for (n, p) in out.placements if n == "Stool"]
        self.assertGreaterEqual(len(stools), 6)
        beside = [s for s in stools if max(abs(s[0] - table[0]), abs(s[1] - table[1])) <= 2]
        # the ring fills up before the count is met; the rest fall back anywhere free
        self.assertGreaterEqual(len(beside), 4, f"stools {stools} not around the table at {table}")

    def test_full_room_reports_failure(self):
        _rect, out = self.layout(5, 5, [(2, 5), (2, 9)],
                                 [FurniturePlan("Chest", "R", 20, "corner")])
        self.assertTrue(out.failures)
        what, count, _reason = out.failures[0]
        self.assertEqual(what, "Chest")
        self.assertLess(count, 20)

    def test_unknown_template(self):
        _rect, out = self.layout(9, 7, [(4, 5)], [FurniturePlan("Sofa", "R", 1, "")])
        self.assertEqual(out.failures, [("Sofa", 0, "unknown template")])


if __name__ == "__main__":
    unittest.main()
