"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const S = require("../schedule.js");

const REGIONS = ["home", "office", "gym", "park"];

function day5() {
  return [
    { start: "21:00", end: "05:00", location: "home", role: "sleep" },
    { start: "05:00", end: "13:00", location: "office", role: "work" },
    { start: "13:00", end: "15:00", location: "gym", role: "leisure" },
    { start: "15:00", end: "19:00", location: "office", role: "work" },
    { start: "19:00", end: "21:00", location: "park", role: "leisure" },
  ];
}

function dayFrom6() {
  return [
    { start: "06:00", end: "09:00", location: "home", role: "leisure" },
    { start: "09:00", end: "17:00", location: "office", role: "work" },
    { start: "17:00", end: "22:00", location: "park", role: "leisure" },
    { start: "22:00", end: "06:00", location: "home", role: "sleep" },
  ];
}

function twoBlockDay() {
  return [
    { start: "00:00", end: "08:00", location: "home", role: "sleep" },
    { start: "08:00", end: "00:00", location: "office", role: "work" },
  ];
}

function assertTiles(segs, label) {
  label = label || "segments";
  assert.ok(segs.length > 0, label + " not empty");
  assert.equal(segs[0].from, 0, label + " start at 0");
  assert.equal(segs[segs.length - 1].to, 1440, label + " end at 1440");
  for (let k = 0; k < segs.length; k++) {
    assert.ok(segs[k].from >= 0 && segs[k].to <= 1440, "inside the bar at " + k);
    assert.ok(segs[k].from < segs[k].to, "positive length at " + k);
    if (k > 0) assert.equal(segs[k].from, segs[k - 1].to, "tiles with neighbour at " + k);
  }
}

function unchanged(sch, fn, label) {
  const before = JSON.stringify(sch);
  fn(sch);
  assert.equal(JSON.stringify(sch), before, (label || "schedule") + " must not change");
}

test("exports exactly the documented API", () => {
  assert.deepEqual(Object.keys(S).sort(), [
    "STEP", "blockAt", "fromMin", "isAllDay", "makeAllDay", "occupancy", "remove",
    "segments", "setBlock", "setBoundary", "split", "toMin", "validate",
  ]);
  assert.equal(S.STEP, 15);
});

test("toMin converts HH:MM to minutes after midnight", () => {
  assert.equal(S.toMin("00:00"), 0);
  assert.equal(S.toMin("09:30"), 570);
  assert.equal(S.toMin("21:00"), 1260);
  assert.equal(S.toMin("23:59"), 1439);
});

test("toMin throws on anything not HH:MM with valid ranges", () => {
  for (const bad of ["24:00", "12:60", "7:30", "0730", "07:3", "ab:cd", "12:30:00", "", null, undefined, 730]) {
    assert.throws(() => S.toMin(bad), TypeError, "should reject " + String(bad));
  }
});

test("fromMin formats minutes as HH:MM", () => {
  assert.equal(S.fromMin(0), "00:00");
  assert.equal(S.fromMin(570), "09:30");
  assert.equal(S.fromMin(1439), "23:59");
});

test("fromMin takes the value modulo 1440 first", () => {
  assert.equal(S.fromMin(-60), "23:00");
  assert.equal(S.fromMin(1440), "00:00");
  assert.equal(S.fromMin(1500), "01:00");
  assert.equal(S.fromMin(-1440), "00:00");
});

test("toMin and fromMin round-trip", () => {
  for (let m = 0; m < 1440; m += 7) assert.equal(S.toMin(S.fromMin(m)), m);
});

test("isAllDay is true only for a single start-equals-end block", () => {
  assert.equal(S.isAllDay(S.makeAllDay("home")), true);
  assert.equal(S.isAllDay([{ start: "06:00", end: "06:00", location: "home", role: "work" }]), true);
  assert.equal(S.isAllDay(day5()), false);
  assert.equal(S.isAllDay(twoBlockDay()), false);
  assert.equal(S.isAllDay([{ start: "00:00", end: "01:00", location: "home", role: "work" }]), false);
  assert.equal(S.isAllDay([]), false);
});

test("segments tiles 0-1440 for a 5-block day with a wrapping block", () => {
  const segs = S.segments(day5());
  assertTiles(segs);
  assert.deepEqual(segs, [
    { index: 0, from: 0, to: 300 },
    { index: 1, from: 300, to: 780 },
    { index: 2, from: 780, to: 900 },
    { index: 3, from: 900, to: 1140 },
    { index: 4, from: 1140, to: 1260 },
    { index: 0, from: 1260, to: 1440 },
  ]);
});

test("segments gives one 0-1440 segment for the all-day block", () => {
  assert.deepEqual(S.segments(S.makeAllDay("home", "sleep")), [{ index: 0, from: 0, to: 1440 }]);
  assertTiles(S.segments(S.makeAllDay("home", "sleep")));
});

test("segments tiles 0-1440 when the first block starts at 06:00", () => {
  const segs = S.segments(dayFrom6());
  assertTiles(segs);
  assert.deepEqual(segs, [
    { index: 3, from: 0, to: 360 },
    { index: 0, from: 360, to: 540 },
    { index: 1, from: 540, to: 1020 },
    { index: 2, from: 1020, to: 1320 },
    { index: 3, from: 1320, to: 1440 },
  ]);
});

test("blockAt covers start inclusively and end exclusively", () => {
  const sch = day5();
  assert.equal(S.blockAt(sch, 0), 0);      // 00:00 inside the wrapped sleep block
  assert.equal(S.blockAt(sch, 1260), 0);   // 21:00 is block 0's start
  assert.equal(S.blockAt(sch, 1259), 4);   // 20:59 is still the park block
  assert.equal(S.blockAt(sch, 300), 1);    // 05:00 is block 0's end, block 1's start
  assert.equal(S.blockAt(sch, 779), 1);    // 12:59 still office
  assert.equal(S.blockAt(sch, 899), 2);    // 14:59 still gym
  assert.equal(S.blockAt(sch, 900), 3);    // 15:00 is block 2's end, block 3's start
});

test("blockAt takes the minute modulo 1440 and returns -1 when empty", () => {
  const sch = day5();
  assert.equal(S.blockAt(sch, 1440), 0);
  assert.equal(S.blockAt(sch, -60), 0);          // 23:00
  assert.equal(S.blockAt(sch, 24 * 60 + 300), 1); // 05:00 next day
  assert.equal(S.blockAt([], 100), -1);
  assert.equal(S.blockAt(S.makeAllDay("home"), 1439), 0);
});

test("validate accepts the valid example schedules", () => {
  assert.deepEqual(S.validate(day5(), REGIONS), []);
  assert.deepEqual(S.validate(dayFrom6(), REGIONS), []);
  assert.deepEqual(S.validate(twoBlockDay(), REGIONS), []);
  assert.deepEqual(S.validate(S.makeAllDay("home", "sleep"), REGIONS), []);
  assert.deepEqual(S.validate(day5(), new Set(REGIONS)), []);
});

test("validate reports an empty schedule", () => {
  const probs = S.validate([], REGIONS);
  assert.equal(probs.length, 1);
  assert.equal(probs[0].index, -1);
  assert.match(probs[0].msg, /empty/);
});

test("validate reports a bad time format", () => {
  const sch = day5();
  sch[2].start = "9:00";
  const probs = S.validate(sch, REGIONS);
  const hits = probs.filter(p => p.index === 2 && /time/.test(p.msg));
  assert.equal(hits.length, 1);
});

test("validate reports a role outside work/leisure/sleep", () => {
  const sch = day5();
  sch[3].role = "nap";
  assert.ok(S.validate(sch, REGIONS).some(p => p.index === 3 && /role/.test(p.msg)));
});

test("validate reports a location outside regionNames (array or Set)", () => {
  const sch = day5();
  sch[4].location = "moon";
  assert.ok(S.validate(sch, REGIONS).some(p => p.index === 4 && /location/.test(p.msg)));
  assert.ok(S.validate(sch, new Set(REGIONS)).some(p => p.index === 4 && /location/.test(p.msg)));
});

test("validate reports start equal to end when there is more than one block", () => {
  const sch = day5();
  sch[2].start = "15:00"; // same as its end
  assert.ok(S.validate(sch, REGIONS).some(p => p.index === 2 && /equals end|equal/.test(p.msg)));
});

test("validate reports a gap between consecutive blocks", () => {
  const sch = day5();
  sch[1].start = "06:00"; // block 0 ends at 05:00
  assert.ok(S.validate(sch, REGIONS).some(p => p.index === 0 && /gap or overlap/.test(p.msg)));
});

test("validate reports an overlap between consecutive blocks", () => {
  const sch = day5();
  sch[1].start = "04:30"; // overlaps block 0
  assert.ok(S.validate(sch, REGIONS).some(p => p.index === 0 && /gap or overlap/.test(p.msg)));
});

test("validate reports a total length that is not 1440", () => {
  // Consecutive and wrapping, but the day is covered twice (3 x 960 minutes).
  const sch = [
    { start: "00:00", end: "16:00", location: "home", role: "work" },
    { start: "16:00", end: "08:00", location: "office", role: "work" },
    { start: "08:00", end: "00:00", location: "gym", role: "leisure" },
  ];
  const probs = S.validate(sch, REGIONS);
  assert.equal(probs.length, 1);
  assert.equal(probs[0].index, -1);
  assert.match(probs[0].msg, /1440/);
});

test("validate reports a single block that is not all-day", () => {
  const sch = [{ start: "08:00", end: "16:00", location: "office", role: "work" }];
  const probs = S.validate(sch, REGIONS);
  assert.ok(probs.some(p => p.index === 0 && /gap or overlap/.test(p.msg)));
  assert.ok(probs.some(p => p.index === -1 && /1440/.test(p.msg)));
});

test("setBoundary moves the boundary to the snapped minute", () => {
  const out = S.setBoundary(day5(), 0, 392); // snaps to 390 = 06:30
  assert.equal(out.length, 5);
  assert.equal(out[0].end, "06:30");
  assert.equal(out[1].start, "06:30");
});

test("setBoundary snaps to the nearest step from both sides", () => {
  assert.equal(S.setBoundary(day5(), 1, 607)[1].end, "10:00"); // 607 -> 600
  assert.equal(S.setBoundary(day5(), 1, 592)[1].end, "09:45"); // 592 -> 585
});

test("setBoundary clamps so block i keeps at least STEP minutes", () => {
  const out = S.setBoundary(day5(), 0, 1262); // snaps to 21:00, block 0's own start
  assert.equal(out[0].start, "21:00");
  assert.equal(out[0].end, "21:15");
  assert.equal(out[1].start, "21:15");
});

test("setBoundary clamps so the next block keeps at least STEP minutes", () => {
  const out = S.setBoundary(day5(), 0, 780); // 13:00 is block 1's end
  assert.equal(out[0].end, "12:45");
  assert.equal(out[1].start, "12:45");
  assert.equal(out[1].end, "13:00");
  assert.equal(S.toMin(out[1].end) - S.toMin(out[1].start), 15);
});

test("setBoundary wraps from the last block to the first", () => {
  const out = S.setBoundary(day5(), 4, 1200); // boundary between block 4 and block 0
  assert.equal(out[4].end, "20:00");
  assert.equal(out[0].start, "20:00");
  assert.deepEqual(S.validate(out, REGIONS), []);
});

test("setBoundary works across midnight for a two-block day", () => {
  const out = S.setBoundary(twoBlockDay(), 0, 720);
  assert.equal(out[0].end, "12:00");
  assert.equal(out[1].start, "12:00");
  assert.equal(out[1].end, "00:00");
  assert.deepEqual(S.validate(out, REGIONS), []);
  assert.equal(S.setBoundary(twoBlockDay(), 0, 5)[0].end, "00:15"); // clamped off midnight
});

test("setBoundary returns an unchanged copy for a single block", () => {
  const sch = S.makeAllDay("home", "sleep");
  const out = S.setBoundary(sch, 0, 300);
  assert.deepEqual(out, sch);
  assert.notEqual(out, sch);
});

test("setBoundary results stay valid and keep tiling for a range of minutes", () => {
  for (const m of [0, 90, 390, 750, 1439]) {
    const out = S.setBoundary(day5(), 1, m);
    assert.deepEqual(S.validate(out, REGIONS), [], "minute " + m);
    assertTiles(S.segments(out), "minute " + m);
  }
});

test("split divides a block keeping location and role", () => {
  const out = S.split(day5(), 1, 600); // 10:00 inside 05:00-13:00
  assert.equal(out.length, 6);
  assert.deepEqual(out[1], { start: "05:00", end: "10:00", location: "office", role: "work" });
  assert.deepEqual(out[2], { start: "10:00", end: "13:00", location: "office", role: "work" });
  assert.deepEqual(S.validate(out, REGIONS), []);
});

test("split snaps the split minute to STEP", () => {
  const out = S.split(day5(), 1, 607);
  assert.equal(out[1].end, "10:00");
  assert.equal(out[2].start, "10:00");
});

test("split returns an unchanged copy when the minute is not STEP inside on both sides", () => {
  const nearStart = S.split(day5(), 1, 305); // snaps to 05:00, the block's start
  assert.deepEqual(nearStart, day5());
  assert.notEqual(nearStart, day5());
  const nearEnd = S.split(day5(), 1, 777); // snaps to 13:00, the block's end
  assert.deepEqual(nearEnd, day5());
  const outside = S.split(day5(), 1, 1000); // 16:40 not inside the block at all
  assert.deepEqual(outside, day5());
});

test("split of the all-day block at 06:00 gives the documented two blocks", () => {
  const out = S.split(S.makeAllDay("home", "sleep"), 0, 360);
  assert.deepEqual(out, [
    { start: "00:00", end: "06:00", location: "home", role: "sleep" },
    { start: "06:00", end: "00:00", location: "home", role: "sleep" },
  ]);
  assert.deepEqual(S.validate(out, REGIONS), []);
});

test("split refuses the all-day block at its own start", () => {
  const sch = [{ start: "06:00", end: "06:00", location: "home", role: "leisure" }];
  const out = S.split(sch, 0, 360);
  assert.deepEqual(out, sch);
  assert.notEqual(out, sch);
});

test("split works on a block that wraps past midnight", () => {
  const out = S.split(day5(), 0, 1380); // 23:00 inside 21:00-05:00
  assert.equal(out.length, 6);
  assert.equal(out[0].end, "23:00");
  assert.equal(out[1].start, "23:00");
  assert.equal(out[1].end, "05:00");
  assert.deepEqual(S.validate(out, REGIONS), []);
});

test("remove merges the removed block's time into the previous block", () => {
  const out = S.remove(day5(), 2); // the gym block 13:00-15:00
  assert.equal(out.length, 4);
  assert.deepEqual(out[1], { start: "05:00", end: "15:00", location: "office", role: "work" });
  assert.deepEqual(S.validate(out, REGIONS), []);
});

test("remove wraps: removing block 0 extends the last block", () => {
  const out = S.remove(day5(), 0); // the sleep block 21:00-05:00
  assert.equal(out.length, 4);
  assert.equal(out[3].start, "19:00");
  assert.equal(out[3].end, "05:00");
  assert.deepEqual(S.validate(out, REGIONS), []);
});

test("remove down to one block makes it all-day", () => {
  const out = S.remove(twoBlockDay(), 1);
  assert.deepEqual(out, [{ start: "00:00", end: "00:00", location: "home", role: "sleep" }]);
  assert.equal(S.isAllDay(out), true);
  assert.deepEqual(S.validate(out, REGIONS), []);
  const out2 = S.remove(twoBlockDay(), 0);
  assert.deepEqual(out2, [{ start: "08:00", end: "08:00", location: "office", role: "work" }]);
  assert.equal(S.isAllDay(out2), true);
});

test("remove on a single block returns an unchanged copy", () => {
  const sch = S.makeAllDay("home");
  const out = S.remove(sch, 0);
  assert.deepEqual(out, sch);
  assert.notEqual(out, sch);
});

test("a chain of split and remove stays valid down to the all-day block", () => {
  let sch = day5();
  sch = S.split(sch, 1, 600);
  sch = S.remove(sch, 3);
  sch = S.remove(sch, 0);
  sch = S.remove(sch, 1);
  assert.deepEqual(S.validate(sch, REGIONS), []);
  assertTiles(S.segments(sch));
  sch = S.remove(sch, 0);
  assert.equal(sch.length, 2);
  assert.deepEqual(S.validate(sch, REGIONS), []);
  sch = S.remove(sch, 0);
  assert.equal(S.isAllDay(sch), true);
});

test("setBlock replaces location and role and ignores other keys", () => {
  const out = S.setBlock(day5(), 2, { location: "park", role: "sleep", start: "00:00", end: "01:00", bogus: 1 });
  assert.equal(out[2].location, "park");
  assert.equal(out[2].role, "sleep");
  assert.equal(out[2].start, "13:00"); // untouched
  assert.equal(out[2].end, "15:00");
  assert.equal("bogus" in out[2], false);
  assert.deepEqual(S.validate(out, REGIONS), []);
});

test("setBlock can change location or role alone and preserves extra block keys", () => {
  const out1 = S.setBlock(day5(), 0, { location: "gym" });
  assert.equal(out1[0].location, "gym");
  assert.equal(out1[0].role, "sleep");
  const out2 = S.setBlock(day5(), 0, { role: "leisure" });
  assert.equal(out2[0].location, "home");
  assert.equal(out2[0].role, "leisure");
  const sch = [{ start: "00:00", end: "00:00", location: "home", role: "leisure", note: "lazy" }];
  assert.equal(S.setBlock(sch, 0, { role: "work" })[0].note, "lazy");
});

test("makeAllDay builds the single all-day block with a default role", () => {
  assert.deepEqual(S.makeAllDay("office", "work"),
    [{ start: "00:00", end: "00:00", location: "office", role: "work" }]);
  assert.deepEqual(S.makeAllDay("home"),
    [{ start: "00:00", end: "00:00", location: "home", role: "leisure" }]);
  assert.equal(S.isAllDay(S.makeAllDay("home")), true);
});

test("occupancy returns 24 hourly buckets for the region", () => {
  const people = [{ id: "a", name: "Ann", schedule: day5() }];
  const occ = S.occupancy(people, "home");
  assert.equal(occ.length, 24);
  for (let h = 0; h < 24; h++) {
    const expected = (h >= 21 || h < 5) ? [{ id: "a", name: "Ann", role: "sleep" }] : [];
    assert.deepEqual(occ[h], expected, "hour " + h);
  }
});

test("occupancy reports the role of the block covering half past each hour", () => {
  const people = [{ id: "a", name: "Ann", schedule: day5() }];
  const office = S.occupancy(people, "office");
  assert.deepEqual(office[6], [{ id: "a", name: "Ann", role: "work" }]);
  assert.deepEqual(office[15], [{ id: "a", name: "Ann", role: "work" }]);
  assert.deepEqual(office[13], []); // gym hour
  assert.deepEqual(office[19], []); // park hour
});

test("occupancy keeps people order and skips other regions", () => {
  const people = [
    { id: "a", name: "Ann", schedule: S.makeAllDay("home", "leisure") },
    { id: "b", name: "Bob", schedule: S.makeAllDay("office", "work") },
    { id: "c", name: "Cal", schedule: S.makeAllDay("home", "sleep") },
  ];
  const home = S.occupancy(people, "home");
  for (const bucket of home) {
    assert.deepEqual(bucket, [
      { id: "a", name: "Ann", role: "leisure" },
      { id: "c", name: "Cal", role: "sleep" },
    ]);
  }
  const office = S.occupancy(people, "office");
  for (const bucket of office) {
    assert.deepEqual(bucket, [{ id: "b", name: "Bob", role: "work" }]);
  }
});

test("setBoundary never mutates its input", () => {
  unchanged(day5(), s => S.setBoundary(s, 0, 390));
  unchanged(day5(), s => S.setBoundary(s, 4, 1200));
  unchanged(twoBlockDay(), s => S.setBoundary(s, 1, 100));
  unchanged(S.makeAllDay("home"), s => S.setBoundary(s, 0, 300));
});

test("split never mutates its input", () => {
  unchanged(day5(), s => S.split(s, 1, 600));
  unchanged(day5(), s => S.split(s, 1, 10)); // refused split
  unchanged(S.makeAllDay("home"), s => S.split(s, 0, 360));
});

test("remove never mutates its input", () => {
  unchanged(day5(), s => S.remove(s, 2));
  unchanged(day5(), s => S.remove(s, 0)); // wrapping remove
  unchanged(twoBlockDay(), s => S.remove(s, 1));
  unchanged(S.makeAllDay("home"), s => S.remove(s, 0)); // refused remove
});

test("setBlock never mutates its input", () => {
  unchanged(day5(), s => S.setBlock(s, 0, { role: "work", location: "gym" }));
});

test("read-only functions never mutate their input", () => {
  unchanged(day5(), s => S.segments(s));
  unchanged(day5(), s => S.blockAt(s, 900));
  unchanged(day5(), s => S.validate(s, REGIONS));
  unchanged(day5(), s => S.isAllDay(s));
  unchanged(day5(), s => S.occupancy([{ id: "a", name: "Ann", schedule: s }], "home"));
});

test("results never alias the input blocks", () => {
  const sch = day5();
  const out = S.setBoundary(sch, 0, 390);
  assert.notEqual(out, sch);
  assert.notEqual(out[0], sch[0]);
  out[0].location = "moon";
  assert.equal(sch[0].location, "home");
});

test("occupancy skips people with no schedule or a broken time", () => {
  const people = [
    { id: "a", name: "A", schedule: undefined },
    { id: "b", name: "B", schedule: [{ start: "9am", end: "17:00", location: "home", role: "work" }] },
    { id: "c", name: "C", schedule: S.makeAllDay("home") },
  ];
  const occ = S.occupancy(people, "home");
  assert.equal(occ.length, 24);
  for (const h of occ) assert.deepEqual(h.map(p => p.id), ["c"]);
});
