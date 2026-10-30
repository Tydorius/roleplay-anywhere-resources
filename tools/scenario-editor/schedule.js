"use strict";
// Daily schedules for the Scenario Editor: blocks {start, end, location, role} that follow each
// other round the clock, any of them wrapping past midnight, or one block with start equal to end
// meaning "here all day". Pure functions; the ones that change a schedule return a copy.

(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Schedule = factory();
})(typeof self !== "undefined" ? self : this, function () {
  var STEP = 15;
  var DAY = 1440;
  var TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
  var ROLES = ["work", "leisure", "sleep"];

  function mod1440(m) { return ((m % DAY) + DAY) % DAY; }

  function snap(m) { return Math.round(m / STEP) * STEP; }

  function okTime(s) { return typeof s === "string" && TIME_RE.test(s); }

  function cloneBlock(b) {
    var c = {};
    for (var k in b) if (Object.prototype.hasOwnProperty.call(b, k)) c[k] = b[k];
    return c;
  }

  function copySchedule(sch) {
    var out = [];
    for (var i = 0; i < sch.length; i++) out.push(cloneBlock(sch[i]));
    return out;
  }

  // Length of a block in minutes; the single start-equals-end block is all day.
  function blockLen(sch, b) {
    if (sch.length === 1 && b.start === b.end) return DAY;
    return mod1440(toMin(b.end) - toMin(b.start));
  }

  function toMin(s) {
    if (!okTime(s)) throw new TypeError("invalid time: " + JSON.stringify(s));
    return Number(s.slice(0, 2)) * 60 + Number(s.slice(3));
  }

  function fromMin(m) {
    var t = mod1440(m);
    var h = Math.floor(t / 60), mm = t % 60;
    return (h < 10 ? "0" + h : "" + h) + ":" + (mm < 10 ? "0" + mm : "" + mm);
  }

  function isAllDay(sch) {
    return !!sch && sch.length === 1 && sch[0].start === sch[0].end;
  }

  function segments(sch) {
    var out = [];
    for (var i = 0; i < sch.length; i++) {
      var b = sch[i];
      var s = toMin(b.start), e = toMin(b.end);
      if (s === e) {
        if (sch.length === 1) out.push({ index: i, from: 0, to: DAY });
      } else if (s < e) {
        out.push({ index: i, from: s, to: e });
      } else {
        out.push({ index: i, from: s, to: DAY });
        out.push({ index: i, from: 0, to: e });
      }
    }
    out.sort(function (a, b) { return a.from - b.from; });
    return out;
  }

  function blockAt(sch, minute) {
    if (sch.length === 0) return -1;
    if (sch.length === 1 && sch[0].start === sch[0].end) return 0;
    var m = mod1440(minute);
    for (var i = 0; i < sch.length; i++) {
      var s = toMin(sch[i].start), e = toMin(sch[i].end);
      if (s < e ? (m >= s && m < e) : (m >= s || m < e)) return i;
    }
    return -1;
  }

  function knownRegion(regionNames, loc) {
    if (regionNames === undefined || regionNames === null) return true;
    if (typeof regionNames.has === "function") return regionNames.has(loc);
    if (Array.isArray(regionNames)) return regionNames.indexOf(loc) !== -1;
    return false;
  }

  function validate(sch, regionNames) {
    var problems = [];
    function add(index, msg) { problems.push({ index: index, msg: msg }); }
    if (!Array.isArray(sch) || sch.length === 0) {
      add(-1, "empty schedule");
      return problems;
    }
    var n = sch.length;
    var timesOk = true;
    var total = 0;
    for (var i = 0; i < n; i++) {
      var b = sch[i];
      var startOk = okTime(b.start), endOk = okTime(b.end);
      if (!startOk || !endOk) {
        timesOk = false;
        add(i, "bad time format: " + (startOk ? JSON.stringify(b.end) : JSON.stringify(b.start)));
      }
      if (ROLES.indexOf(b.role) === -1) {
        add(i, "role must be work, leisure or sleep, got " + JSON.stringify(b.role));
      }
      if (!knownRegion(regionNames, b.location)) {
        add(i, "location " + JSON.stringify(b.location) + " is not a known region");
      }
      if (n > 1 && b.start === b.end) {
        add(i, "start equals end, only allowed for a single all-day block");
      }
      if (startOk && endOk) total += blockLen(sch, b);
    }
    for (var k = 0; k < n; k++) {
      var nx = (k + 1) % n;
      if (sch[k].end !== sch[nx].start) {
        add(k, "gap or overlap: end of block " + k + " must equal start of block " + nx);
      }
    }
    if (timesOk && total !== DAY) add(-1, "total length is " + total + " minutes, expected 1440");
    return problems;
  }

  function setBoundary(sch, i, minute) {
    var n = sch.length;
    if (n <= 1 || i < 0 || i >= n) return copySchedule(sch);
    var j = (i + 1) % n;
    var s = toMin(sch[i].start);
    var span = blockLen(sch, sch[i]) + blockLen(sch, sch[j]);
    if (span < 2 * STEP) return copySchedule(sch);
    var d = mod1440(snap(minute) - s);
    if (d < STEP) d = STEP;
    if (d > span - STEP) d = span - STEP;
    var boundary = mod1440(s + d);
    var out = copySchedule(sch);
    out[i].end = fromMin(boundary);
    out[j].start = fromMin(boundary);
    return out;
  }

  function split(sch, i, minute) {
    var n = sch.length;
    if (i < 0 || i >= n) return copySchedule(sch);
    var b = sch[i];
    var len = blockLen(sch, b);
    if (len < 2 * STEP) return copySchedule(sch);
    var m = mod1440(snap(minute));
    var d = mod1440(m - toMin(b.start));
    if (d < STEP || d > len - STEP) return copySchedule(sch);
    var out = copySchedule(sch);
    var second = cloneBlock(b);
    second.start = fromMin(m);
    out[i].end = fromMin(m);
    out.splice(i + 1, 0, second);
    return out;
  }

  function remove(sch, i) {
    var n = sch.length;
    if (n <= 1 || i < 0 || i >= n) return copySchedule(sch);
    var out = copySchedule(sch);
    var removedEnd = out[i].end;
    out.splice(i, 1);
    var prev = i === 0 ? out[out.length - 1] : out[i - 1];
    if (out.length === 1) prev.end = prev.start;
    else prev.end = removedEnd;
    return out;
  }

  function setBlock(sch, i, changes) {
    var out = copySchedule(sch);
    if (i < 0 || i >= out.length || !changes) return out;
    if (changes.location !== undefined) out[i].location = changes.location;
    if (changes.role !== undefined) out[i].role = changes.role;
    return out;
  }

  function makeAllDay(location, role) {
    if (role === undefined) role = "leisure";
    return [{ start: "00:00", end: "00:00", location: location, role: role }];
  }

  function occupancy(people, regionName) {
    var result = [];
    for (var h = 0; h < 24; h++) {
      var minute = mod1440(h * 60 + 30);
      var here = [];
      for (var p = 0; p < people.length; p++) {
        var person = people[p];
        var bi;
        try { bi = blockAt(person.schedule || [], minute); } catch (e) { bi = -1; }   // a broken time: leave them out
        if (bi !== -1 && person.schedule[bi].location === regionName) {
          here.push({ id: person.id, name: person.name, role: person.schedule[bi].role });
        }
      }
      result.push(here);
    }
    return result;
  }

  return {toMin, fromMin, isAllDay, segments, blockAt, validate, setBoundary, split, remove,
          setBlock, makeAllDay, occupancy, STEP};
});
