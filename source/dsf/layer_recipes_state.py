"""Temperature-by-layer RECIPES, the armed run: the PURE state machine (no I/O, no clock of its own). One RecipeRun is one recipe armed for ONE job file.

It is the multi-track sibling of pellet_layers.Run and keeps its rules: it only proposes events while the machine is "processing"; a pause HOLDS
(nothing sent, still armed); cancel, end or a lost job DISARM and leave the temperatures as they are; a heater that is off is never switched on and,
after the first change of its track, one that went off ends the run; the board refusing a code turns that TRACK off. What to send comes from
layer_recipes_plan.commands_for (the same function the preview uses). The caller (layer_recipes_run.py) does the I/O and answers with commit() / rejected().

Events: {"type": "apply", "track", "codes": [..], "temps", "layer", "key", "notes"} to send, {"type": "note", ...} to record, {"type": "disarm", ...}
the run is over. Tracks of the recipe: "extruder" (tool heaters, M568) and "bed" (bed zones, one M140 P<bed> each; `snap["bed_heaters"]` maps a bed number
to its heater and `snap["bed_config"]` is the bed-zones configuration read now).
"""
import layer_recipes_plan as plan
import pellet_layers as pl

TRACKS = plan.TRACKS


class RecipeRun:
    def __init__(self, name, recipe, file, armed_at, armed_by=None, file_bases=None):
        self.name = name
        self.recipe = recipe
        self.file = file
        self.armed_at = armed_at
        self.armed_by = armed_by or {}
        self.file_bases = file_bases or []   # per layer {"extruder": [..] | None, "bed": ..}: what the FILE holds at the layer's start (scanned once at arm)
        self.seen_job = False
        self.ended = False
        self.reason = None
        self.phase = "waiting"
        self.layer = None
        self.key = None
        self.changes = 0
        self.last_change_at = None
        self.tracks = {t: {"applied": None, "layer": None, "key": None, "limited": [], "off": False, "waiting": False, "held": False,
                           "mismatch": 0, "noted": False, "over_layer": None, "base": None, "board_base": None} for t in TRACKS if recipe["tracks"].get(t)}

    # -- helpers --

    def has(self, track):
        return track in self.tracks

    def _end(self, key, warn, **params):
        self.ended = True
        self.phase = "ended"
        self.reason = {"key": key, "params": params, "warn": warn}
        return [{"type": "disarm", "reason": key, "params": params, "warn": warn}]

    def disarm(self):
        return [] if self.ended else self._end("layer_recipes_off_by_user", False)

    def rejected(self, track, answer):
        """The board refused a code of `track`: that track is off; the run ends when no track is left."""
        self.tracks[track]["off"] = True
        params = {"track": track, "answer": str(answer or "")[:160]}
        if all(t["off"] for t in self.tracks.values()):
            return self._end("layer_recipes_off_rejected", True, **params)
        return [{"type": "note", "key": "layer_recipes_track_rejected", "params": params, "warn": True}]

    def commit(self, event, now):
        t = self.tracks[event["track"]]
        t["applied"], t["layer"], t["key"] = list(event["temps"]), event["layer"], event["key"]
        t["limited"] = list(event.get("notes") or [])
        t["noted"], t["mismatch"], t["over_layer"] = False, 0, None
        t["base"] = list(event["base"])
        self.layer, self.key = event["layer"], event["key"]
        self.changes += 1
        self.last_change_at = now
        self.phase = "running"

    def view(self):
        """What the page shows (no messages: the reason travels as key + params)."""
        tracks = {}
        for name, t in self.tracks.items():
            track = self.recipe["tracks"][name]
            nxt = pl.next_point(track, t["key"] if t["key"] is not None else -1)
            tracks[name] = {"applied": t["applied"], "next": nxt, "limited": bool(t["limited"]), "notes": list(t["limited"]), "off": t["off"],
                           "overridden": t["noted"], "overridden_layer": t["over_layer"], "base": t["base"]}
        return {"armed": not self.ended, "phase": self.phase, "recipe": self.name, "file": self.file, "layer": self.layer, "key": self.key,
                "tracks": tracks, "changes": self.changes, "last_change_at": self.last_change_at, "armed_by": self.armed_by.get("user", ""),
                "reason": self.reason}

    # -- reading what each track needs from the object model --

    def _extruder_ctx(self, snap, t):
        track = self.recipe["tracks"]["extruder"]
        tool = next((x for x in snap["tools"] if x.get("number") == track["tool"]), None)
        if tool is None:
            return None, self._end("layer_recipes_off_tool_missing", True, tool=track["tool"])
        if list(tool.get("heaters") or []) != track["heaters"]:
            return None, self._end("layer_recipes_off_heaters_changed", True, tool=track["tool"])
        models = []
        for h in track["heaters"]:
            m = snap["heaters"][h] if h < len(snap["heaters"]) else None
            if not isinstance(m, dict):
                return None, self._end("layer_recipes_off_heater_missing", True, heater=h)
            models.append(m)
        end = self._heaters_state(track["heaters"], models, t)
        if end:
            return None, end
        t["held"] = tool.get("state") != "active" or any(m.get("state") == "standby" for m in models)
        if t["waiting"] or t["held"]:
            return None, []
        caps = plan.track_caps(track, models)
        if caps is None:
            return None, self._end("layer_recipes_off_no_limit", True)
        active = [pl._number(a) for a in (tool.get("active") or [])]
        if len(active) != len(models) or any(a is None for a in active):
            return None, self._end("layer_recipes_off_no_active", True)
        return {"caps": caps, "active": active}, []

    def _bed_ctx(self, snap, t):
        track = self.recipe["tracks"]["bed"]
        config = snap.get("bed_config")
        problem = plan.bed_problem(track, config, snap.get("bed_problem"))
        if problem:
            return None, self._end("layer_recipes_off_bed_config", True, problem=problem[0])
        slots = snap.get("bed_heaters") or []
        heaters, models = [], []
        for zone in track["zones"]:
            h = slots[zone] if zone < len(slots) else None
            m = snap["heaters"][h] if isinstance(h, int) and not isinstance(h, bool) and 0 <= h < len(snap["heaters"]) else None
            if not isinstance(m, dict):
                return None, self._end("layer_recipes_off_zone_missing", True, zone=zone)
            heaters.append(h)
            models.append(m)
        end = self._heaters_state(heaters, models, t)
        if end:
            return None, end
        t["held"] = any(m.get("state") == "standby" for m in models)
        if t["waiting"] or t["held"]:
            return None, []
        caps = plan.track_caps(track, models, config["max_temp"])
        if caps is None:
            return None, self._end("layer_recipes_off_no_limit", True)
        active = [pl._number(m.get("active")) for m in models]
        if any(a is None for a in active):
            return None, self._end("layer_recipes_off_no_active", True)
        return {"caps": caps, "active": active, "zones": {"zones": config["zones"], "max_temp": config["max_temp"]}}, []

    def _heaters_state(self, heaters, models, t):
        """Ends the run on a heater in fault; a heater that is off is waited for before the first change and ends the run after it."""
        t["waiting"] = False
        for h, m in zip(heaters, models):
            if m.get("state") in pl.LOST_HEATER_STATES:
                return self._end("layer_recipes_off_heater_fault", True, heater=h, state=str(m.get("state")))
        for h, m in zip(heaters, models):
            if m.get("state") == "off":
                if t["applied"] is None:
                    t["waiting"] = True  # never switch a heater on: wait for the G-code to heat it
                    return None
                return self._end("layer_recipes_off_heater_off", True, heater=h)
        return None

    def _base(self, name, layer, active):
        """The base of a track at `layer`: per heater / zone what the file holds when the layer starts, else what the board held at the first tick
        (remembered: the recipe's own changes must not move it). None when a heater has neither (then the track is not computed)."""
        t = self.tracks[name]
        if t["board_base"] is None:
            t["board_base"] = list(active)
        row = self.file_bases[layer - 1] if 1 <= layer <= len(self.file_bases) else {}
        return plan.resolve_base(row.get(name), t["board_base"])

    def _overridden(self, t, active):
        if t["applied"] is None:
            return []
        if any(abs(a - x) > pl.OVERRIDE_TOL for a, x in zip(active, t["applied"])):
            t["mismatch"] += 1
            if t["mismatch"] >= pl.OVERRIDE_POLLS and not t["noted"]:
                t["noted"], t["over_layer"] = True, t["layer"]
                return [{"type": "note", "key": "layer_recipes_overridden", "params": {"layer": t["layer"]}, "warn": False}]
        else:
            t["mismatch"], t["noted"], t["over_layer"] = 0, False, None  # the board matches again: the episode is over, a later one is noted again
        return []

    # -- the step --

    def step(self, snap, now):
        if self.ended:
            return []
        status = snap["status"]
        if not self.seen_job and now - self.armed_at > pl.ARM_TTL_S:
            return self._end("layer_recipes_off_expired", False)
        in_job = status == "processing" or status in pl.HOLD_STATES
        if not in_job:
            if status == "simulating" or not self.seen_job:
                self.phase = "waiting"  # a simulation heats nothing; a job that has not started yet is just waited for
                return []
            return self._end("layer_recipes_off_job_ended", False)
        if snap["file"] != self.file:
            return self._end("layer_recipes_off_other_job", True, file=str(snap["file"] or ""))
        self.seen_job = True
        ctx, events = {}, []
        for name, t in self.tracks.items():
            if t["off"]:
                continue
            got, end = (self._extruder_ctx if name == "extruder" else self._bed_ctx)(snap, t)
            if end:
                return end
            if got is not None:
                ctx[name] = got
                events.extend(self._overridden(t, got["active"]))
        live = [n for n, t in self.tracks.items() if not t["off"]]
        if status in pl.HOLD_STATES or (live and all(self.tracks[n]["held"] for n in live)):
            self.phase = "holding"
            return events
        if live and all(self.tracks[n]["waiting"] for n in live):
            self.phase = "waiting_heat"
            return events
        layer = snap["layer"] or pl.layer_from_z(snap["layer_z"], snap["z"])
        if layer is None:
            self.phase = "waiting_layer"
            return events
        first = self.recipe["tracks"][live[0]] if live else None
        key = plan.key_for(first["axis"], layer, snap["layer_z"], snap["z"]) if first else None
        if key is None:
            self.phase = "waiting_layer"
            return events
        self.phase = "running"
        for n in ctx:
            ctx[n]["base"] = self._base(n, layer, ctx[n]["active"])
        sub = {"tracks": {n: self.recipe["tracks"][n] for n in ctx if self.tracks[n]["layer"] is None or layer > self.tracks[n]["layer"]}}
        if not sub["tracks"]:
            return events
        last = {n: ({"layer": t["layer"], "temps": t["applied"]} if t["applied"] is not None else None) for n, t in self.tracks.items()}
        result = plan.commands_for(sub, {"layer": layer, "key": key}, last, ctx)
        for name in TRACKS:
            res = result[name]
            if res is None:
                continue
            t = self.tracks[name]
            t["limited"] = list(res["notes"])
            if res["held"]:
                continue  # no legal move now: it keeps what it has and tries again at the next layer
            if not res["send"]:
                t["layer"], t["key"], t["applied"], t["base"] = layer, key, list(res["temps"]), list(res["base"])  # the board already has it: nothing to send
                self.layer, self.key = layer, key
                continue
            events.append({"type": "apply", "track": name, "codes": [res["code"]] if name == "extruder" else list(res["codes"]),
                           "temps": res["temps"], "base": res["base"], "raw": res["raw"], "layer": layer, "key": key, "notes": res["notes"]})  # applied moves in commit()
        return events
