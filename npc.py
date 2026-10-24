"""The NPC body: movement, a smoothly turning head (so the vision cone sweeps
believably), speech bubbles and alert icons. All thinking is in self.brain."""
from __future__ import annotations

import math

from pygame.math import Vector2

import config as C
from brain.brain import Brain
from entities import Entity


class NPC(Entity):
    kind = "npc"

    def __init__(self, name: str, grid: tuple[int, int], recorder):
        super().__init__(name, grid, 11, C.NPC_COL)
        self.desired_facing = Vector2(self.facing)
        self.carrying = 0                 # coins in pocket, not yet deposited
        self.speech = ""
        self.speech_until = 0.0
        self.alert = ""                   # "!" or "?" shown above the head
        self.alert_until = 0.0
        self.brain = Brain(self, recorder)

    # --- body ------------------------------------------------------------------------
    def face(self, direction: Vector2) -> None:
        """NPCs turn their head gradually instead of snapping (see _turn)."""
        if direction.length_squared() > 1e-6:
            self.desired_facing = direction.normalize()

    def look_around(self, now: float, speed: float = 1.5) -> None:
        """Idle head scan: sweep the vision cone left and right."""
        self.desired_facing = self.desired_facing.rotate(math.sin(now * speed) * 2)

    def _turn(self, dt: float) -> None:
        angle = self.facing.angle_to(self.desired_facing)
        angle = (angle + 180) % 360 - 180
        step = C.NPC_TURN_RATE * dt
        self.facing = self.facing.rotate(max(-step, min(step, angle)))

    def say(self, text: str, now: float, duration: float = 2.6) -> None:
        self.speech, self.speech_until = text, now + duration

    def set_alert(self, icon: str, now: float, duration: float = 1.6) -> None:
        self.alert, self.alert_until = icon, now + duration

    def update(self, world, dt: float) -> None:
        self.brain.update(world, dt)
        self._turn(dt)
