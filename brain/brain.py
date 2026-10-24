"""Brain: the per-frame cognitive loop.

    SENSE  -> Perception.sense()               (what is visible / audible right now)
    UPDATE -> _process_perception()            (turn senses into memories & feelings)
    FEEL   -> Drives.update(), Memory.update() (needs grow, trust drifts, memories fade)
    THINK  -> UtilityReasoner.evaluate()       (every DECISION_INTERVAL seconds)
    ACT    -> current Action.update()          (every frame)
"""
from __future__ import annotations

import config as C
from .actions import build_default_actions
from .context import BrainContext
from .drives import Drives
from .memory import Memory
from .perception import Perception, PerceptionSnapshot
from .utility import Status, UtilityReasoner


def trust_band(trust: float) -> str:
    if trust < 0.3:
        return "HOSTILE"
    if trust < 0.5:
        return "WARY"
    if trust < 0.7:
        return "NEUTRAL"
    return "FRIENDLY"


class Brain:
    def __init__(self, npc, recorder):
        self.npc = npc
        self.recorder = recorder
        self.perception = Perception(npc)
        self.memory = Memory(npc)
        self.drives = Drives()
        self.actions = build_default_actions()
        self.reasoner = UtilityReasoner(self.actions, C.COMMITMENT_BONUS)
        self.current = None
        self.scores = []                      # last ranked ScoredAction list (telemetry)
        self.snapshot = PerceptionSnapshot()
        self.ctx: BrainContext | None = None
        self.decision_timer = 0.0
        self.last_stash_ok = True
        self.got_gift = False
        self.bands: dict[int, str] = {}       # last trust band per entity, for milestones

    # ===================================================================================
    def update(self, world, dt: float) -> None:
        self.snapshot = self.perception.sense(world)
        self._process_perception(world)
        self.drives.update(dt, threat_visible=bool(self.snapshot.of_kind("wolf")))
        self.memory.update(dt, world.time)
        self.ctx = BrainContext.build(self, world)
        self._check_trust_milestones(world.time)

        self.decision_timer -= dt
        if self.decision_timer <= 0 or self.current is None:
            self.decision_timer = C.DECISION_INTERVAL
            self.think()

        if self.current is not None:
            status = self.current.update(self.npc, self.ctx, dt)
            if status != Status.RUNNING:
                self._end_current(status)

    # --- THINK ---------------------------------------------------------------------------
    def think(self) -> None:
        self.scores = self.reasoner.evaluate(self.ctx, self.current)
        best = self.scores[0]
        if best.action is not self.current and best.score > 0:
            self._switch_to(best)

    def _switch_to(self, best) -> None:
        old = self.current
        if old is not None:
            old.stop(self.npc, self.ctx)
        self.current = best.action
        self.current.start(self.npc, self.ctx)
        top = {sa.action.name: round(sa.score, 3) for sa in self.scores[:4]}
        drives = {k: round(v, 3) for k, v in self.drives.as_dict().items()}
        self.recorder.flag("decision",
                           f"{self.npc.name}: {old.label if old else 'None'} -> {best.action.label} ({best.score:.2f})",
                           importance=1, actor=self.npc.name, scores=top, drives=drives)

    def _end_current(self, status: str) -> None:
        a = self.current
        a.stop(self.npc, self.ctx)
        a.finish(self.ctx)
        self.recorder.flag("action_end", f"{self.npc.name}: {a.label} {status}", importance=0, actor=self.npc.name)
        self.current = None
        self.decision_timer = 0.0

    def interrupt(self) -> None:
        """Force an immediate re-think (used when something dramatic happens)."""
        self.decision_timer = 0.0

    # --- SENSE -> MEMORY -------------------------------------------------------------------
    def _process_perception(self, world) -> None:
        now, npc, mem = world.time, self.npc, self.memory
        snap = self.snapshot

        # 1) one-frame events first, so a witnessed theft isn't also "deduced"
        for se in snap.events:
            ev = se.event
            if ev.kind == "theft" and ev.data["chest"].owner_id == npc.id:
                rec = mem.record_for(ev.actor)
                if se.how == "sight":
                    mem.record_theft(rec, now, witnessed=True)
                    mem.set_stash(ev.data["chest"].gold, now)
                    self.drives.greed += C.THEFT_GREED_SPIKE
                    self.drives.clamp()
                    npc.say("HEY! THIEF!", now)
                    npc.set_alert("!", now)
                    self.recorder.flag("theft_witnessed", f"{npc.name} SAW {rec.name} steal (trust -> {rec.trust:.2f})",
                                       importance=3, actor=npc.name, trust=round(rec.trust, 3), thefts=rec.thefts)
                    self.interrupt()
                else:
                    mem.note_noise(ev.pos, now)
                    mem.remember("Heard a creak from my chest...", now)
                    npc.say("Was that... my chest?", now)
                    npc.set_alert("?", now)
                    self.recorder.flag("theft_heard", f"{npc.name} HEARD the chest but didn't see who",
                                       importance=2, actor=npc.name)
                    self.interrupt()

        # 2) entities: update last-known positions, react to threats
        for s in snap.entities:
            e = s.entity
            rec, fresh = mem.observe_entity(e, now)
            if e.kind == "wolf":
                self.drives.raise_fear(0.55 + 0.45 * (1 - min(s.dist / C.VISION_RANGE, 1)))
                mem.note_threat(e.pos, now)
                if fresh:
                    self.drives.raise_fear(C.STARTLE_FEAR)   # first sight of a threat is a jolt
                    npc.say("A WOLF!", now)
                    npc.set_alert("!", now)
                    mem.remember("Spotted a wolf!", now)
                    self.recorder.flag("threat_spotted", f"{npc.name} spotted a wolf ({s.how})",
                                       importance=2, actor=npc.name)
                    self.interrupt()
            elif e.kind == "player" and fresh:
                mem.remember(f"Saw {e.name} (trust {rec.trust:.2f})", now)
                if rec.trust >= 0.7:
                    npc.say("Oh, it's my friend!", now)
                elif rec.trust < 0.3:
                    npc.say("YOU again...", now)

        # 3) objects: remember resources, count the stash when close enough
        for obj, dist in snap.objects:
            if obj.kind in ("food", "coin"):
                if mem.observe_resource(obj, now):
                    mem.remember(f"Spotted {obj.kind} at {obj.grid}", now)
            elif obj is world.chest and obj.owner_id == npc.id and dist <= C.STASH_INSPECT_RANGE:
                self.inspect_stash(obj, now)

        # 4) memories contradicted by sight: "the food I remembered is gone"
        for rec in list(mem.resources.values()):
            if self.perception.can_see(world, rec.pos) and world.object_at(rec.grid, rec.kind) is None:
                mem.forget_resource(rec.kind, rec.grid)
                mem.remember(f"The {rec.kind} at {rec.grid} is gone", now)
                target = getattr(self.current, "target", None)
                if getattr(target, "grid", None) == rec.grid and getattr(target, "kind", None) == rec.kind:
                    # he was walking toward something that only exists in his head
                    npc.say("Huh? The food is gone..." if rec.kind == "food" else "Someone beat me to it.", now)
                    npc.set_alert("?", now)
                    self.recorder.flag("false_memory", f"{npc.name} reached for a {rec.kind} that's no longer there",
                                       importance=2, actor=npc.name)

    def inspect_stash(self, chest, now: float) -> None:
        """Compare the chest against what we *believe* is in it. A shortfall with
        no witnessed theft means someone stole while we weren't looking."""
        mem = self.memory
        if mem.stash_belief is None:
            mem.set_stash(chest.gold, now)
            mem.remember(f"My chest holds {chest.gold} gold", now)
            return
        missing = mem.stash_belief - chest.gold
        if missing > 0:
            self.last_stash_ok = False
            self.drives.greed += C.THEFT_GREED_SPIKE
            self.drives.clamp()
            suspect = mem.suspect_near(chest.pos, now)
            if suspect:
                for _ in range(missing):
                    mem.record_theft(suspect, now, witnessed=False)
                self.npc.say(f"{missing} gold missing... it was {suspect.name}!", now)
                self.npc.set_alert("!", now)
                self.recorder.flag("theft_deduced",
                                   f"{self.npc.name} DEDUCED {suspect.name} stole {missing} gold (trust -> {suspect.trust:.2f})",
                                   importance=3, actor=self.npc.name, missing=missing, trust=round(suspect.trust, 3))
            else:
                mem.remember(f"{missing} gold missing. No idea who took it.", now)
                self.npc.say("Who took my gold?!", now)
                self.recorder.flag("theft_unsolved", f"{self.npc.name} found {missing} gold missing, no suspect",
                                   importance=2, actor=self.npc.name)
            self.interrupt()
        else:
            self.last_stash_ok = True
        mem.set_stash(chest.gold, now)

    # --- external stimuli ----------------------------------------------------------------
    def on_gift(self, giver, world) -> None:
        rec = self.memory.record_for(giver)
        self.memory.record_gift(rec, world.time)
        self.drives.hunger -= C.GIFT_SATIATION
        self.drives.clamp()
        self.got_gift = True
        self.npc.say("For me? Thank you!", world.time)
        self.recorder.flag("gift", f"{giver.name} gave {self.npc.name} food (trust -> {rec.trust:.2f})",
                           importance=2, actor=giver.name, trust=round(rec.trust, 3), gifts=rec.gifts)
        self.interrupt()

    def on_attacked(self, attacker, world) -> None:
        self.drives.raise_fear(1.0)
        self.memory.note_threat(attacker.pos, world.time)
        self.memory.remember(f"Bitten by a {attacker.name.lower()}!", world.time)
        self.npc.say("OW! Get away!", world.time)
        self.npc.set_alert("!", world.time)
        self.recorder.flag("attacked", f"{attacker.name} bit {self.npc.name}! Fear -> 1.0",
                           importance=3, actor=self.npc.name)
        self.interrupt()

    def _check_trust_milestones(self, now: float) -> None:
        for eid, rec in self.memory.entities.items():
            if rec.kind != "player":
                continue
            band = trust_band(rec.trust)
            prev = self.bands.get(eid)
            if prev is not None and band != prev:
                self.memory.remember(f"{rec.name} is now {band} to me", now)
                self.recorder.flag("trust_band", f"{self.npc.name} now sees {rec.name} as {band} "
                                   f"(was {prev}, trust {rec.trust:.2f})",
                                   importance=3, actor=self.npc.name, band=band, trust=round(rec.trust, 3))
            self.bands[eid] = band
