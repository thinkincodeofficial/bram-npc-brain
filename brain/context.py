"""BrainContext: a per-frame bundle of everything an action needs to score itself.
Considerations read from this object only, never from the world directly, so
every decision is based on what the NPC *perceives and remembers*."""
from __future__ import annotations

import math
from dataclasses import dataclass

import config as C


@dataclass
class BrainContext:
    npc: object
    world: object
    memory: object
    drives: object
    snap: object
    time: float
    player: object = None
    player_seen: object = None      # SeenEntity if the player is perceived right now
    player_rec: object = None       # EntityRecord (memory) or None if never met
    threat: object = None           # closest perceived wolf (SeenEntity) or None
    chest: object = None

    @classmethod
    def build(cls, brain, world) -> "BrainContext":
        ctx = cls(brain.npc, world, brain.memory, brain.drives, brain.snapshot, world.time)
        ctx.player = world.player
        if ctx.player is not None:
            ctx.player_seen = brain.snapshot.sees(ctx.player)
            ctx.player_rec = brain.memory.entities.get(ctx.player.id)
        wolves = brain.snapshot.of_kind("wolf")
        ctx.threat = min(wolves, key=lambda s: s.dist) if wolves else None
        ctx.chest = world.chest if world.chest and world.chest.owner_id == brain.npc.id else None
        return ctx

    # --- convenience readouts used by considerations -----------------------------------
    @property
    def player_visible(self) -> bool:
        return self.player_seen is not None

    @property
    def player_trust(self) -> float:
        return self.player_rec.trust if self.player_rec else C.TRUST_START

    @property
    def player_thefts(self) -> int:
        return self.player_rec.thefts if self.player_rec else 0

    def secs_since_player(self) -> float:
        return self.player_rec.seconds_since_seen(self.time) if self.player_rec else math.inf

    def dist_factor(self, pos) -> float:
        """1.0 when close, fading to 0.4 at ~14 tiles: far things are less appealing."""
        d = self.npc.pos.distance_to(pos)
        return 1.0 - min(d / (14 * C.TILE), 1.0) * 0.6

    def nearest_known(self, kind: str):
        recs = self.memory.known(kind)
        return min(recs, key=lambda r: self.npc.pos.distance_to(r.pos)) if recs else None

    def threat_level(self) -> float:
        """1 if a threat is visible, fading over 6 s of remembered danger."""
        if self.threat:
            return 1.0
        age = self.time - self.memory.threat_time
        return max(0.0, 1.0 - age / 6.0) * 0.8

    def player_near_chest(self) -> float:
        if not (self.player_seen and self.chest):
            return 0.0
        d = self.player.pos.distance_to(self.chest.pos)
        return max(0.0, 1.0 - d / (4 * C.TILE))
