"""Concrete behaviours the Utility Reasoner chooses between.

Each Action = a list of Considerations (scored 0..1 and multiplied) + a small
state machine (start / update / stop). No action knows about any other; the
"personality" emerges from how their scores compete as drives and memory change.
"""
from __future__ import annotations

import math

import config as C
from .utility import Action, Consideration, Status, clamp01, logistic

ARRIVED, MOVING, UNREACHABLE = "arrived", "moving", "unreachable"


def walk_to(npc, ctx, grid, dt: float, run: bool = False) -> str:
    if npc.grid == grid and not npc.path:
        return ARRIVED
    if npc.dest != grid and not npc.set_destination(ctx.world, grid):
        return UNREACHABLE
    if npc.follow_path(dt, C.NPC_RUN_SPEED if run else C.NPC_WALK_SPEED):
        return ARRIVED
    return MOVING


def calm(ctx) -> float:
    return 1.0 - 0.85 * ctx.drives.fear


# ------------------------------------------------------------------------------------
class Wander(Action):
    """Baseline 'nothing better to do'. A flat score every other action must beat."""
    name, label, weight, color = "wander", "Wander", 0.15, (150, 160, 180)

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.target = ctx.world.random_floor(npc.grid, 5, min_dist=2)
        self.pause = 0.0
        self.arrived = False

    def update(self, npc, ctx, dt):
        if self.arrived:
            self.pause -= dt
            npc.look_around(ctx.time)
            return Status.SUCCESS if self.pause <= 0 else Status.RUNNING
        res = walk_to(npc, ctx, self.target, dt)
        if res == UNREACHABLE:
            return Status.FAILED
        if res == ARRIVED:
            self.arrived, self.pause = True, ctx.world.rng.uniform(1.0, 2.5)
        return Status.RUNNING


class Eat(Action):
    name, label, weight, color = "eat", "Eat Food", 1.0, C.HUNGER_COL

    def build_considerations(self):
        return [
            Consideration("hunger", lambda c: logistic(c.drives.hunger, 0.5, 9)),
            Consideration("food known", lambda c: c.dist_factor(f.pos) if (f := c.nearest_known("food")) else 0),
            Consideration("calm", calm),
        ]

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.target = ctx.nearest_known("food")

    def update(self, npc, ctx, dt):
        t = self.target
        if t is None or ("food", t.grid) not in ctx.memory.resources:
            return Status.FAILED          # it vanished from memory (someone took it)
        res = walk_to(npc, ctx, t.grid, dt)
        if res == UNREACHABLE:
            ctx.memory.forget_resource("food", t.grid)
            return Status.FAILED
        if res != ARRIVED:
            return Status.RUNNING
        food = ctx.world.object_at(t.grid, "food")
        ctx.memory.forget_resource("food", t.grid)
        if food is None:
            npc.say("Huh? The food is gone...", ctx.time)
            return Status.FAILED
        ctx.world.remove_object(food)
        before = ctx.drives.hunger
        ctx.drives.hunger -= C.EAT_SATIATION
        ctx.drives.clamp()
        npc.say("Mmm. Much better.", ctx.time)
        ctx.memory.remember("Ate some food", ctx.time)
        npc.brain.recorder.flag("npc_ate", f"{npc.name} ate food (hunger {before:.2f} -> {ctx.drives.hunger:.2f})",
                                importance=2, actor=npc.name)
        return Status.SUCCESS


class CollectCoin(Action):
    name, label, weight, color = "collect", "Collect Coin", 0.8, C.GREED_COL

    def build_considerations(self):
        return [
            Consideration("greed", lambda c: c.drives.greed),
            Consideration("coin known", lambda c: c.dist_factor(r.pos) if (r := c.nearest_known("coin")) else 0),
            Consideration("calm", calm),
            Consideration("not starving", lambda c: 1 - 0.7 * c.drives.hunger),
        ]

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.target = ctx.nearest_known("coin")

    def update(self, npc, ctx, dt):
        t = self.target
        if t is None or ("coin", t.grid) not in ctx.memory.resources:
            return Status.FAILED
        res = walk_to(npc, ctx, t.grid, dt)
        if res == UNREACHABLE:
            ctx.memory.forget_resource("coin", t.grid)
            return Status.FAILED
        if res != ARRIVED:
            return Status.RUNNING
        coin = ctx.world.object_at(t.grid, "coin")
        ctx.memory.forget_resource("coin", t.grid)
        if coin is None:
            npc.say("Someone beat me to it.", ctx.time)
            return Status.FAILED
        ctx.world.remove_object(coin)
        npc.carrying += 1
        npc.say(f"A coin! ({npc.carrying} carried)", ctx.time)
        return Status.SUCCESS


class Deposit(Action):
    name, label, weight, color = "deposit", "Deposit Gold", 0.85, (240, 180, 40)

    def build_considerations(self):
        return [
            Consideration("carrying", lambda c: 0.4 + 0.6 * min(c.npc.carrying / 3, 1) if c.npc.carrying else 0),
            Consideration("greed", lambda c: 0.5 + 0.5 * c.drives.greed),
            Consideration("calm", calm),
        ]

    def can_run(self, ctx):
        return super().can_run(ctx) and ctx.chest is not None

    def update(self, npc, ctx, dt):
        res = walk_to(npc, ctx, ctx.chest.grid, dt)
        if res == UNREACHABLE:
            return Status.FAILED
        if res != ARRIVED:
            return Status.RUNNING
        n = npc.carrying
        ctx.chest.gold += n
        npc.carrying = 0
        ctx.memory.set_stash(ctx.chest.gold, ctx.time)
        ctx.drives.greed -= C.DEPOSIT_GREED_RELIEF * n
        ctx.drives.clamp()
        npc.say(f"+{n} gold. Safe and sound.", ctx.time)
        ctx.memory.remember(f"Deposited {n} gold (stash {ctx.chest.gold})", ctx.time)
        npc.brain.recorder.flag("deposit", f"{npc.name} deposited {n} gold -> stash {ctx.chest.gold}",
                                importance=1, actor=npc.name)
        return Status.SUCCESS


class CheckStash(Action):
    """Walk to the chest to count it. The *count* happens in Brain.inspect_stash,
    which is where thefts get deduced."""
    name, label, weight, color = "check_stash", "Check Stash", 0.7, (210, 170, 90)

    def build_considerations(self):
        return [
            Consideration("greed", lambda c: 0.3 + 0.7 * c.drives.greed),
            Consideration("unchecked for", lambda c: min((c.time - c.memory.stash_checked_time) / 45, 1)),
            Consideration("suspicion", self._suspicion),
            Consideration("calm", calm),
        ]

    @staticmethod
    def _suspicion(c) -> float:
        if c.time - c.memory.noise_time < 20:
            return 1.0
        rec = c.player_rec
        if rec and c.chest and rec.last_seen_pos and rec.seconds_since_seen(c.time) < 20 \
                and rec.last_seen_pos.distance_to(c.chest.pos) < 4 * C.TILE and rec.trust < 0.6:
            return 0.9
        return 0.45

    def can_run(self, ctx):
        return super().can_run(ctx) and ctx.chest is not None

    def update(self, npc, ctx, dt):
        res = walk_to(npc, ctx, ctx.chest.grid, dt)
        if res == UNREACHABLE:
            return Status.FAILED
        if res != ARRIVED:
            return Status.RUNNING
        if npc.brain.last_stash_ok:
            npc.say("All accounted for.", ctx.time)
        return Status.SUCCESS


class Guard(Action):
    name, label, weight, color = "guard", "Guard Chest", 1.0, (240, 120, 120)

    def build_considerations(self):
        return [
            Consideration("player near chest", lambda c: c.player_near_chest()),
            Consideration("distrust", lambda c: logistic(1 - c.player_trust, 0.45, 10)),
            Consideration("greed", lambda c: 0.5 + 0.5 * c.drives.greed),
            Consideration("calm", calm),
        ]

    def can_run(self, ctx):
        return super().can_run(ctx) and ctx.chest is not None

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.away = 0.0
        npc.say("Hands off. That chest is MINE.", ctx.time)

    def update(self, npc, ctx, dt):
        chest = ctx.chest
        if ctx.player_near_chest() <= 0:
            self.away += dt
            if self.away > 2.0:
                return Status.SUCCESS
        else:
            self.away = 0.0
        if self.elapsed(ctx) > 10:
            return Status.SUCCESS
        # stand on the tile next to the chest that is closest to the player
        p = ctx.player.pos
        options = [(chest.grid[0] + dx, chest.grid[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   if (dx or dy) and ctx.world.is_walkable(chest.grid[0] + dx, chest.grid[1] + dy)]
        spot = min(options, key=lambda g: ctx.world.tile_center(*g).distance_to(p)) if options else chest.grid
        if walk_to(npc, ctx, spot, dt, run=True) == ARRIVED and ctx.player_visible:
            npc.face(p - npc.pos)
        return Status.RUNNING


class Confront(Action):
    name, label, weight, color = "confront", "Confront Thief", 1.1, C.DISTRUST_COL
    cooldown = 10.0

    def build_considerations(self):
        return [
            Consideration("player visible", lambda c: 1.0 if c.player_visible else 0.0),
            Consideration("grudge", lambda c: logistic(1 - c.player_trust, 0.62, 12)),
            Consideration("evidence", lambda c: 1.0 if c.player_thefts else 0.0),  # never chase the innocent
            Consideration("courage", lambda c: 1 - c.drives.fear),
        ]

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.repath = 0.0
        npc.say("YOU! Get back here!", ctx.time)
        npc.set_alert("!", ctx.time)

    def update(self, npc, ctx, dt):
        p = ctx.player
        if ctx.secs_since_player() > 3 or self.elapsed(ctx) > 12:
            npc.say("...Coward.", ctx.time)
            return Status.FAILED
        self.repath -= dt
        if self.repath <= 0:
            npc.set_destination(ctx.world, p.grid, force=True)
            self.repath = 0.3
        npc.follow_path(dt, C.NPC_RUN_SPEED)
        if npc.pos.distance_to(p.pos) > C.INTERACT_RANGE:
            return Status.RUNNING
        if p.coins > 0:
            p.coins -= 1
            npc.carrying += 1
            ctx.memory.adjust_trust(ctx.player_rec, C.TRUST_RESTITUTION)
            npc.say("I'll take THAT back!", ctx.time)
            p.notify(f"{npc.name} took a coin back!", ctx.time)
            ctx.memory.remember("Took a coin back from Player", ctx.time)
            npc.brain.recorder.flag("confront", f"{npc.name} confronted the player and reclaimed a coin",
                                    importance=3, actor=npc.name, trust=round(ctx.player_trust, 3))
        else:
            npc.say("Stay away from my things!", ctx.time)
            npc.brain.recorder.flag("confront", f"{npc.name} confronted the player (no coins to reclaim)",
                                    importance=2, actor=npc.name)
        return Status.SUCCESS


class Investigate(Action):
    """Go to where something suspicious happened (a noise, or where a distrusted
    player was last seen) and look around."""
    name, label, weight, color = "investigate", "Investigate", 0.75, (240, 220, 120)
    cooldown = 6.0

    def __init__(self):
        super().__init__()
        self.resolved_time = -1e9

    def lead(self, c):
        """Returns (strength, position, timestamp, source) of the best lead, or None.
        A lost player only counts after 2 s out of sight, otherwise merely turning
        the head would create and destroy the lead every frame."""
        m = c.memory
        if m.noise_pos is not None and m.noise_time > self.resolved_time and c.time - m.noise_time < 15:
            return 0.9 * (1 - (c.time - m.noise_time) / 15) + 0.1, m.noise_pos, m.noise_time, "noise"
        rec = c.player_rec
        if rec and not c.player_visible and rec.last_seen_time > self.resolved_time:
            age = rec.seconds_since_seen(c.time)
            if 2.0 <= age < 25:
                strength = logistic(1 - rec.trust, 0.55, 10) * (1 - age / 25)
                return strength, rec.last_seen_pos, rec.last_seen_time, "player"
        return None

    def build_considerations(self):
        return [
            Consideration("lead", lambda c: l[0] if (l := self.lead(c)) else 0.0),
            Consideration("calm", calm),
        ]

    def start(self, npc, ctx):
        super().start(npc, ctx)
        lead = self.lead(ctx)
        self.target = ctx.world.to_grid(lead[1]) if lead else npc.grid
        self.lead_time = lead[2] if lead else ctx.time
        self.source = lead[3] if lead else "noise"
        self.look = 0.0
        npc.set_alert("?", ctx.time)
        npc.say("Hmm? What was that..." if self.source == "noise" else "Where did you go...?", ctx.time)

    def update(self, npc, ctx, dt):
        if self.source == "player" and ctx.player_visible:
            self.resolved_time = ctx.time
            npc.say("There you are.", ctx.time)
            return Status.SUCCESS
        if self.look > 0:
            self.look -= dt
            npc.look_around(ctx.time, speed=2.5)
            if self.look <= 0:
                self.resolved_time = max(self.lead_time, ctx.time)
                npc.say("Nothing here.", ctx.time)
                return Status.SUCCESS
            return Status.RUNNING
        res = walk_to(npc, ctx, self.target, dt)
        if res == UNREACHABLE:
            self.resolved_time = ctx.time
            return Status.FAILED
        if res == ARRIVED:
            self.look = 2.5
        return Status.RUNNING


class Follow(Action):
    """Friendship behaviour: tag along with a trusted player for a while."""
    name, label, weight, color = "follow", "Follow Friend", 0.6, C.TRUST_COL
    cooldown = 12.0

    def build_considerations(self):
        return [
            Consideration("player visible", lambda c: 1.0 if c.player_visible else 0.0),
            Consideration("trust", lambda c: logistic(c.player_trust, 0.68, 12)),
            Consideration("calm", calm),
            Consideration("not starving", lambda c: 1 - 0.6 * c.drives.hunger),
        ]

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.repath = 0.0
        npc.say("Hey, friend! Wait up!", ctx.time)

    def update(self, npc, ctx, dt):
        if ctx.secs_since_player() > 2 or self.elapsed(ctx) > 7:
            return Status.SUCCESS
        p = ctx.player
        if npc.pos.distance_to(p.pos) > 2.2 * C.TILE:
            self.repath -= dt
            if self.repath <= 0:
                npc.set_destination(ctx.world, p.grid, force=True)
                self.repath = 0.5
            npc.follow_path(dt, C.NPC_WALK_SPEED * 1.2)
        else:
            npc.stop_moving()
            npc.face(p.pos - npc.pos)
        return Status.RUNNING


class Beg(Action):
    """Hungry, no food anywhere it knows of, and a not-hostile player nearby."""
    name, label, weight, color = "beg", "Ask For Food", 0.9, (255, 170, 120)
    cooldown = 15.0

    def build_considerations(self):
        return [
            Consideration("hunger", lambda c: logistic(c.drives.hunger, 0.6, 10)),
            Consideration("no food known", lambda c: 0.15 if c.memory.known("food") else 1.0),
            Consideration("player visible", lambda c: 1.0 if c.player_visible else 0.0),
            Consideration("trust", lambda c: logistic(c.player_trust, 0.35, 12)),
        ]

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.repath = 0.0
        self.waiting = 0.0
        npc.brain.got_gift = False
        npc.say("Please... do you have any food?", ctx.time)

    def update(self, npc, ctx, dt):
        if npc.brain.got_gift:
            return Status.SUCCESS
        if ctx.secs_since_player() > 3:
            return Status.FAILED
        p = ctx.player
        if npc.pos.distance_to(p.pos) > 1.6 * C.TILE:
            self.repath -= dt
            if self.repath <= 0:
                npc.set_destination(ctx.world, p.grid, force=True)
                self.repath = 0.5
            npc.follow_path(dt, C.NPC_WALK_SPEED)
        else:
            npc.stop_moving()
            npc.face(p.pos - npc.pos)
            self.waiting += dt
            if self.waiting > 6:
                npc.say("...Fine. I'll find my own.", ctx.time)
                return Status.FAILED
        return Status.RUNNING


class Flee(Action):
    name, label, weight, color = "flee", "Flee to Safety", 1.3, C.FEAR_COL

    def build_considerations(self):
        return [
            Consideration("fear", lambda c: logistic(c.drives.fear, 0.35, 10)),
            Consideration("threat", lambda c: c.threat_level()),
        ]

    def start(self, npc, ctx):
        super().start(npc, ctx)
        self.retarget = 0.0
        self.target = None
        self.reached_refuge = False
        npc.set_alert("!", ctx.time)
        npc.say("RUN!", ctx.time)

    def stop(self, npc, ctx):
        """However the flee ends, if he made it to cover and the threat is gone, he exhales."""
        super().stop(npc, ctx)
        if self.reached_refuge and not ctx.threat:
            npc.say("Phew... safe.", ctx.time)
            npc.brain.recorder.flag("safe", f"{npc.name} reached safety", importance=2, actor=npc.name)

    def _pick_refuge(self, npc, ctx):
        world, m = ctx.world, ctx.memory
        danger = ctx.threat.entity.pos if ctx.threat else (m.threat_pos or npc.pos)
        home = min(world.home_tiles, key=lambda g: world.tile_center(*g).distance_to(npc.pos)) \
            if world.home_tiles else None
        # go home unless the threat is closer to home than we are
        if home and world.tile_center(*home).distance_to(danger) > world.tile_center(*home).distance_to(npc.pos):
            return home
        candidates = [world.random_floor(npc.grid, 9, min_dist=4) for _ in range(14)]
        return max(candidates, key=lambda g: world.tile_center(*g).distance_to(danger))

    def update(self, npc, ctx, dt):
        self.retarget -= dt
        if self.target is None or (ctx.threat and self.retarget <= 0):
            self.target = self._pick_refuge(npc, ctx)
            npc.stop_moving()
            self.retarget = 1.0
        res = walk_to(npc, ctx, self.target, dt, run=True)
        if res == UNREACHABLE:
            self.target = None
        elif res == ARRIVED:
            if ctx.threat:
                self.target = None
            else:
                self.reached_refuge = True
                npc.look_around(ctx.time, speed=4)
                if ctx.drives.fear < 0.2:
                    return Status.SUCCESS
        return Status.RUNNING


def build_default_actions() -> list[Action]:
    return [Wander(), Eat(), CollectCoin(), Deposit(), CheckStash(), Guard(),
            Confront(), Investigate(), Follow(), Beg(), Flee()]
