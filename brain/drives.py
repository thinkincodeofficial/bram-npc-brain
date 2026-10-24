"""Internal drives: slow-moving needs that bias every decision.

  hunger - rises steadily; eating or receiving food lowers it
  fear   - spikes when a threat is seen or attacks; decays when safe
  greed  - rises steadily; depositing gold lowers it, losing gold spikes it
"""
from __future__ import annotations

from dataclasses import dataclass

import config as C


@dataclass
class Drives:
    hunger: float = 0.25
    fear: float = 0.0
    greed: float = 0.35

    def update(self, dt: float, threat_visible: bool) -> None:
        self.hunger += C.HUNGER_RATE * dt
        self.greed += C.GREED_RATE * dt
        if not threat_visible:
            self.fear -= C.FEAR_DECAY * dt
        self.clamp()

    def raise_fear(self, level: float) -> None:
        self.fear = max(self.fear, level)
        self.clamp()

    def clamp(self) -> None:
        self.hunger = max(0.0, min(1.0, self.hunger))
        self.fear = max(0.0, min(1.0, self.fear))
        self.greed = max(0.0, min(1.0, self.greed))

    def as_dict(self) -> dict[str, float]:
        return {"hunger": self.hunger, "fear": self.fear, "greed": self.greed}
