"""Utility AI core: response curves, Considerations, the Action base class and
the Reasoner that scores every action and picks the winner.

Score of an action = weight * product(considerations), with Dave Mark's
"compensation factor" so actions with many considerations aren't unfairly
punished just for having more multiplications.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable


# --- response curves (map a 0..1 input to a 0..1 desire) ---------------------------
def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def linear(x: float, slope: float = 1.0, offset: float = 0.0) -> float:
    return clamp01(slope * x + offset)


def quadratic(x: float, power: float = 2.0) -> float:
    return clamp01(x) ** power


def logistic(x: float, midpoint: float = 0.5, steepness: float = 10.0) -> float:
    return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))


def inverse(x: float) -> float:
    return 1.0 - clamp01(x)


@dataclass
class Consideration:
    """One named factor of a decision, e.g. 'hunger' or 'food is known'."""
    name: str
    evaluate: Callable[[object], float]

    def score(self, ctx) -> float:
        return clamp01(self.evaluate(ctx))


class Status:
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Action:
    """Base class. Subclasses define considerations and start/update/stop."""
    name = "action"
    label = "Action"
    weight = 1.0
    color = (200, 200, 200)
    cooldown = 0.0           # seconds after finishing before it can win again

    def __init__(self):
        self.considerations: list[Consideration] = self.build_considerations()
        self.ready_at = 0.0
        self.started_at = 0.0

    def build_considerations(self) -> list[Consideration]:
        return []

    def can_run(self, ctx) -> bool:
        """Hard gate (cooldowns, missing prerequisites) checked before scoring."""
        return ctx.time >= self.ready_at

    def score(self, ctx) -> tuple[float, dict[str, float]]:
        if not self.can_run(ctx):
            return 0.0, {"cooldown": 0.0}
        cons = self.considerations
        if not cons:
            return self.weight, {}
        mod = 1.0 - 1.0 / len(cons)
        total, breakdown = 1.0, {}
        for c in cons:
            v = c.score(ctx)
            breakdown[c.name] = v
            total *= v + (1.0 - v) * mod * v
            if total <= 0.0:
                break
        return total * self.weight, breakdown

    # lifecycle ---------------------------------------------------------------------------
    def start(self, npc, ctx) -> None:
        self.started_at = ctx.time

    def update(self, npc, ctx, dt: float) -> str:
        return Status.SUCCESS

    def stop(self, npc, ctx) -> None:
        npc.stop_moving()

    def finish(self, ctx) -> None:
        self.ready_at = ctx.time + self.cooldown

    def elapsed(self, ctx) -> float:
        return ctx.time - self.started_at


@dataclass
class ScoredAction:
    action: Action
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    committed: bool = False


class UtilityReasoner:
    def __init__(self, actions: list[Action], commitment_bonus: float):
        self.actions = actions
        self.commitment_bonus = commitment_bonus

    def evaluate(self, ctx, current: Action | None) -> list[ScoredAction]:
        """Score every action. The running action gets a small inertia bonus so the
        NPC doesn't flicker between two near-equal options."""
        scored = []
        for a in self.actions:
            s, br = a.score(ctx)
            committed = a is current and s > 0
            if committed:
                s += self.commitment_bonus
            scored.append(ScoredAction(a, s, br, committed))
        scored.sort(key=lambda sa: sa.score, reverse=True)
        return scored
