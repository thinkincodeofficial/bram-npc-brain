"""Bodies that move around the world: the shared Entity base, the Player and
the Wolf threat. The NPC (which owns a Brain) lives in npc.py."""
from __future__ import annotations

from itertools import count

import pygame
from pygame.math import Vector2

import config as C
from pathfinding import astar
from world import Chest, World

_entity_ids = count(1)


class Entity:
    kind = "entity"

    def __init__(self, name: str, grid: tuple[int, int], radius: int, color):
        self.id = next(_entity_ids)
        self.name = name
        self.pos = World.tile_center(*grid)
        self.radius = radius
        self.color = color
        self.facing = Vector2(1, 0)
        self.path: list[tuple[int, int]] = []
        self.dest: tuple[int, int] | None = None
        self.alive = True

    @property
    def grid(self) -> tuple[int, int]:
        return World.to_grid(self.pos)

    def face(self, direction: Vector2) -> None:
        if direction.length_squared() > 1e-6:
            self.facing = direction.normalize()

    # --- navigation -----------------------------------------------------------
    def set_destination(self, world: World, grid: tuple[int, int], force: bool = False) -> bool:
        """Plan an A* path to `grid`. Returns False if the tile is unreachable."""
        if not force and grid == self.dest and self.path:
            return True
        path = astar(world, self.grid, grid)
        if path is None:
            self.path, self.dest = [], None
            return False
        self.path, self.dest = path[1:], grid
        return True

    def follow_path(self, dt: float, speed: float) -> bool:
        """Advance along the current path. Returns True once the path is exhausted."""
        step = speed * dt
        while self.path and step > 0:
            target = World.tile_center(*self.path[0])
            to = target - self.pos
            dist = to.length()
            if dist <= step:
                self.pos = target
                self.path.pop(0)
                step -= dist
            else:
                self.face(to)
                self.pos += to / dist * step
                step = 0
        return not self.path

    def stop_moving(self) -> None:
        self.path, self.dest = [], None

    # --- free movement (player) -------------------------------------------------
    def _collides(self, world: World, pos: Vector2) -> bool:
        r = self.radius - 1
        for cx, cy in ((pos.x - r, pos.y - r), (pos.x + r, pos.y - r),
                       (pos.x - r, pos.y + r), (pos.x + r, pos.y + r)):
            if world.is_wall(int(cx // C.TILE), int(cy // C.TILE)):
                return True
        return False

    def move_free(self, world: World, vel: Vector2, dt: float) -> None:
        """Axis-separated movement so the body slides along walls."""
        if vel.length_squared() == 0:
            return
        self.face(vel)
        nx = Vector2(self.pos.x + vel.x * dt, self.pos.y)
        if not self._collides(world, nx):
            self.pos = nx
        ny = Vector2(self.pos.x, self.pos.y + vel.y * dt)
        if not self._collides(world, ny):
            self.pos = ny

    def draw(self, surf: pygame.Surface) -> None:
        pygame.draw.circle(surf, self.color, self.pos, self.radius)
        pygame.draw.circle(surf, (20, 20, 24), self.pos, self.radius, 2)
        pygame.draw.circle(surf, (255, 255, 255), self.pos + self.facing * (self.radius - 4), 3)


class Player(Entity):
    kind = "player"

    def __init__(self, grid: tuple[int, int]):
        super().__init__("Player", grid, 11, C.PLAYER_COL)
        self.coins = 0
        self.food = 0
        self.toast = ""          # short HUD feedback text
        self.toast_time = 0.0

    def notify(self, text: str, time: float) -> None:
        self.toast, self.toast_time = text, time

    def handle_movement(self, keys, world: World, dt: float) -> None:
        d = Vector2((keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT]),
                    (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP]))
        if d.length_squared():
            self.move_free(world, d.normalize() * C.PLAYER_SPEED, dt)

    def interact(self, world: World, recorder) -> None:
        """E key: steal from a chest, or pick up food / coins."""
        obj = world.nearest_object(self.pos, C.INTERACT_RANGE)
        if obj is None:
            self.notify("Nothing to interact with", world.time)
            return
        if isinstance(obj, Chest):
            if obj.gold <= 0:
                self.notify("The chest is empty", world.time)
                return
            obj.gold -= 1
            self.coins += 1
            self.notify("You stole 1 gold!", world.time)
            world.emit("theft", obj.pos, self, chest=obj)
            recorder.flag("player_theft", f"Player stole from the chest ({obj.gold} left)",
                          importance=2, actor=self.name, chest_gold=obj.gold)
        elif obj.kind == "food":
            world.remove_object(obj)
            self.food += 1
            self.notify("Picked up food", world.time)
            world.emit("pickup", obj.pos, self, item="food")
        elif obj.kind == "coin":
            world.remove_object(obj)
            self.coins += 1
            self.notify("Picked up a coin", world.time)
            world.emit("pickup", obj.pos, self, item="coin")

    def give_food(self, world: World, npcs: list, recorder) -> None:
        """G key: hand food to an adjacent NPC (the only way to *earn* trust)."""
        near = [n for n in npcs if n.pos.distance_to(self.pos) <= C.INTERACT_RANGE * 1.4]
        if not near:
            self.notify("No one close enough", world.time)
            return
        if self.food <= 0:
            self.notify("You have no food to give", world.time)
            return
        npc = min(near, key=lambda n: n.pos.distance_to(self.pos))
        self.food -= 1
        world.emit("gift", npc.pos, self, target=npc, item="food")
        npc.brain.on_gift(self, world)
        self.notify(f"Gave food to {npc.name}", world.time)


class Wolf(Entity):
    """A roaming threat. It hunts NPCs it can see, bites, then retreats."""
    kind = "wolf"

    def __init__(self, grid: tuple[int, int]):
        super().__init__("Wolf", grid, 12, C.WOLF_COL)
        self.state = "prowl"
        self.age = 0.0
        self.repath = 0.0
        self.retreat_timer = 0.0

    def update(self, world: World, npcs: list, dt: float, recorder) -> None:
        self.age += dt
        if self.age > C.WOLF_LIFETIME:
            self.alive = False
            recorder.flag("wolf_left", "The wolf wandered off", importance=1)
            return
        prey = min(npcs, key=lambda n: n.pos.distance_to(self.pos), default=None)
        sees = (prey is not None and prey.pos.distance_to(self.pos) <= C.WOLF_SIGHT
                and world.line_of_sight(self.pos, prey.pos))

        if self.state == "retreat":
            self.retreat_timer -= dt
            if self.follow_path(dt, C.WOLF_SPEED) or self.retreat_timer <= 0:
                self.state = "prowl"
            return

        if sees:
            if self.state != "hunt":
                recorder.flag("wolf_hunt", f"Wolf started hunting {prey.name}", importance=1)
            self.state = "hunt"
            self.repath -= dt
            if self.repath <= 0:
                self.set_destination(world, prey.grid, force=True)
                self.repath = 0.4
            self.follow_path(dt, C.WOLF_SPEED)
            if self.pos.distance_to(prey.pos) <= self.radius + prey.radius + C.WOLF_BITE_RANGE * 0.3:
                prey.brain.on_attacked(self, world)
                self.state = "retreat"
                self.retreat_timer = 4.0
                self.set_destination(world, world.random_floor(self.grid, 10, min_dist=6), force=True)
        else:
            self.state = "prowl"
            if self.follow_path(dt, C.WOLF_SPEED * 0.55):
                self.set_destination(world, world.random_floor(self.grid, 6))

    def draw(self, surf: pygame.Surface) -> None:
        side = Vector2(-self.facing.y, self.facing.x)
        for s in (-1, 1):
            base = self.pos + self.facing * 4 + side * 7 * s
            pygame.draw.polygon(surf, (110, 110, 120),
                                [base, base + self.facing * 9 + side * 2 * s, base - side * 5 * s])
        super().draw(surf)
        pygame.draw.circle(surf, (255, 60, 60), self.pos + self.facing * 6 + side * 4, 2)
        pygame.draw.circle(surf, (255, 60, 60), self.pos + self.facing * 6 - side * 4, 2)
