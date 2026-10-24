"""Perception: what the NPC can sense *this frame*.

Three senses:
  * sight   - a vision cone (FOV + range) whose rays are blocked by walls (DDA raycast)
  * hearing - world events within HEARING_RADIUS are heard even through walls
  * touch   - anything inside TOUCH_RADIUS is noticed, even from behind
The output is a PerceptionSnapshot; the Brain turns snapshots into Memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pygame.math import Vector2

import config as C


@dataclass
class SeenEntity:
    entity: object
    dist: float
    how: str            # "sight" | "touch"


@dataclass
class SensedEvent:
    event: object
    how: str            # "sight" | "hearing"


@dataclass
class PerceptionSnapshot:
    entities: list[SeenEntity] = field(default_factory=list)
    objects: list[tuple[object, float]] = field(default_factory=list)
    events: list[SensedEvent] = field(default_factory=list)

    def sees(self, entity) -> SeenEntity | None:
        for s in self.entities:
            if s.entity is entity:
                return s
        return None

    def of_kind(self, kind: str) -> list[SeenEntity]:
        return [s for s in self.entities if s.entity.kind == kind]


def _wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


class Perception:
    def __init__(self, owner, fov: float = C.VISION_FOV, view_range: float = C.VISION_RANGE,
                 hearing: float = C.HEARING_RADIUS):
        self.owner = owner
        self.fov = fov
        self.range = view_range
        self.hearing = hearing

    def in_cone(self, point: Vector2) -> bool:
        to = point - self.owner.pos
        d = to.length()
        if d > self.range:
            return False
        if d < 1e-3:
            return True
        return abs(_wrap(self.owner.facing.angle_to(to))) <= self.fov / 2

    def can_see(self, world, point: Vector2) -> bool:
        return self.in_cone(point) and world.line_of_sight(self.owner.pos, point)

    def sense(self, world) -> PerceptionSnapshot:
        snap = PerceptionSnapshot()
        me = self.owner.pos
        for e in world.entities:
            if e is self.owner or not e.alive:
                continue
            d = e.pos.distance_to(me)
            if d <= C.TOUCH_RADIUS:
                snap.entities.append(SeenEntity(e, d, "touch"))
            elif self.can_see(world, e.pos):
                snap.entities.append(SeenEntity(e, d, "sight"))
        for o in world.objects:
            if o.alive and self.can_see(world, o.pos):
                snap.objects.append((o, o.pos.distance_to(me)))
        for ev in world.events:
            actor_pos = getattr(ev.actor, "pos", ev.pos)
            if self.can_see(world, actor_pos) or self.can_see(world, ev.pos):
                snap.events.append(SensedEvent(ev, "sight"))
            elif ev.pos.distance_to(me) <= self.hearing:
                snap.events.append(SensedEvent(ev, "hearing"))
        return snap

    def cone_polygon(self, world, rays: int = C.CONE_RAYS) -> list[Vector2]:
        """Wall-clipped cone outline for the debug overlay (one DDA ray per step)."""
        eye = self.owner.pos
        pts = [Vector2(eye)]
        for i in range(rays + 1):
            ang = -self.fov / 2 + self.fov * i / rays
            end = eye + self.owner.facing.rotate(ang) * self.range
            pts.append(world.raycast(eye, end)[1])
        return pts
