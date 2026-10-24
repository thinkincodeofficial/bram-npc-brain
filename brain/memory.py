"""Memory: what the NPC *believes*, which can differ from what is true.

  * EntityRecord   - per-entity trust, thefts, gifts, last known position and a
                     breadcrumb buffer of past sightings (used to deduce culprits)
  * ResourceRecord - remembered food / coin locations that expire if unseen
  * stash belief   - how much gold the NPC thinks is in its chest
  * event log      - a short-term rolling buffer of narrated memories
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from pygame.math import Vector2

import config as C


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class EntityRecord:
    entity_id: int
    name: str
    kind: str
    trust: float = C.TRUST_START
    thefts: int = 0
    gifts: int = 0
    times_seen: int = 0
    last_seen_pos: Vector2 | None = None
    last_seen_time: float = -1e9
    sightings: deque = field(default_factory=lambda: deque(maxlen=C.SIGHTING_BUFFER))

    @property
    def baseline(self) -> float:
        """Where trust drifts back to. Grudges and goodwill shift it permanently."""
        return _clamp01(C.TRUST_START - C.GRUDGE_PER_THEFT * self.thefts
                        + C.GOODWILL_PER_GIFT * self.gifts)

    def seconds_since_seen(self, now: float) -> float:
        return now - self.last_seen_time


@dataclass
class ResourceRecord:
    kind: str
    grid: tuple[int, int]
    pos: Vector2
    seen_time: float


class Memory:
    def __init__(self, owner):
        self.owner = owner
        self.entities: dict[int, EntityRecord] = {}
        self.resources: dict[tuple[str, tuple[int, int]], ResourceRecord] = {}
        self.log: deque[tuple[float, str]] = deque(maxlen=C.EVENT_LOG_SIZE)
        self.stash_belief: int | None = None
        self.stash_checked_time = -1e9
        self.threat_pos: Vector2 | None = None
        self.threat_time = -1e9
        self.noise_pos: Vector2 | None = None     # last suspicious sound
        self.noise_time = -1e9

    # --- narration ---------------------------------------------------------------
    def remember(self, text: str, now: float) -> None:
        self.log.appendleft((now, text))

    # --- entities -----------------------------------------------------------------
    def record_for(self, entity) -> EntityRecord:
        rec = self.entities.get(entity.id)
        if rec is None:
            rec = EntityRecord(entity.id, entity.name, entity.kind)
            self.entities[entity.id] = rec
        return rec

    def observe_entity(self, entity, now: float) -> tuple[EntityRecord, bool]:
        """Update last-known location. Returns (record, is_new_sighting_after_gap)."""
        rec = self.record_for(entity)
        fresh = rec.seconds_since_seen(now) > 5.0
        if fresh:
            rec.times_seen += 1
        rec.last_seen_pos = Vector2(entity.pos)
        rec.last_seen_time = now
        if not rec.sightings or now - rec.sightings[-1][0] >= C.SIGHTING_INTERVAL:
            rec.sightings.append((now, Vector2(entity.pos)))
        return rec, fresh

    def trust_of(self, entity_id: int) -> float:
        rec = self.entities.get(entity_id)
        return rec.trust if rec else C.TRUST_START

    def adjust_trust(self, rec: EntityRecord, delta: float) -> None:
        rec.trust = _clamp01(rec.trust + delta)

    def record_theft(self, rec: EntityRecord, now: float, witnessed: bool) -> None:
        rec.thefts += 1
        self.adjust_trust(rec, C.TRUST_WITNESSED_THEFT if witnessed else C.TRUST_DEDUCED_THEFT)
        how = "SAW" if witnessed else "deduced"
        self.remember(f"{how} {rec.name} steal gold (trust {rec.trust:.2f})", now)

    def record_gift(self, rec: EntityRecord, now: float) -> None:
        rec.gifts += 1
        self.adjust_trust(rec, C.TRUST_GIFT)
        self.remember(f"{rec.name} gave me food (trust {rec.trust:.2f})", now)

    def suspect_near(self, pos: Vector2, now: float) -> EntityRecord | None:
        """Most recent non-threat entity whose breadcrumbs put them near `pos`."""
        best, best_t = None, now - C.SUSPECT_WINDOW
        for rec in self.entities.values():
            if rec.kind == "wolf":
                continue
            for t, p in rec.sightings:
                if t >= best_t and p.distance_to(pos) <= C.SUSPECT_RADIUS:
                    best, best_t = rec, t
        return best

    # --- resources --------------------------------------------------------------------
    def observe_resource(self, obj, now: float) -> bool:
        key = (obj.kind, obj.grid)
        new = key not in self.resources
        self.resources[key] = ResourceRecord(obj.kind, obj.grid, Vector2(obj.pos), now)
        return new

    def forget_resource(self, kind: str, grid: tuple[int, int]) -> None:
        self.resources.pop((kind, grid), None)

    def known(self, kind: str) -> list[ResourceRecord]:
        return [r for r in self.resources.values() if r.kind == kind]

    # --- threats & noises ----------------------------------------------------------------
    def note_threat(self, pos: Vector2, now: float) -> None:
        self.threat_pos, self.threat_time = Vector2(pos), now

    def note_noise(self, pos: Vector2, now: float) -> None:
        self.noise_pos, self.noise_time = Vector2(pos), now

    # --- stash -------------------------------------------------------------------------
    def set_stash(self, gold: int, now: float) -> None:
        self.stash_belief, self.stash_checked_time = gold, now

    # --- per-frame upkeep ----------------------------------------------------------------
    def update(self, dt: float, now: float) -> None:
        for rec in self.entities.values():
            gap = rec.baseline - rec.trust
            step = C.TRUST_DRIFT * dt
            rec.trust += max(-step, min(step, gap))
        for key, r in list(self.resources.items()):
            if now - r.seen_time > C.RESOURCE_MEMORY_TTL:
                del self.resources[key]
                self.remember(f"Forgot where the {r.kind} at {r.grid} was", now)
