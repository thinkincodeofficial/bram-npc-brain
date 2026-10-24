"""The village grid: walls, environmental objects, the event bus and the
DDA raycaster that powers NPC line-of-sight."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from itertools import count

import pygame
from pygame.math import Vector2

import config as C

# Legend:  # wall   . floor   F food   $ coin   C chest (NPC stash)
#          H home rug (NPC safe zone)   P player spawn   N NPC spawn
LAYOUT = [
    "##############################",
    "#............#...............#",
    "#..F.........#........C......#",
    "#............#...............#",
    "#....HH.........$............#",
    "#....HH......#...............#",
    "#............#...............#",
    "######.#######.......####.####",
    "#............................#",
    "#....$..................#....#",
    "#.......................#.F..#",
    "#.......P...............#....#",
    "#.......................#....#",
    "#####......N............######",
    "#............................#",
    "#.....######.................#",
    "#.....#....#.......$.........#",
    "#.....#.F.......$............#",
    "#.....#....#.........F.......#",
    "#.....######.................#",
    "#............................#",
    "##############################",
]

_ids = count(1)


@dataclass(eq=False)
class WorldObject:
    """Anything that sits on a tile and can be perceived: food, coins, chests."""
    kind: str
    grid: tuple[int, int]
    id: int = field(default_factory=lambda: next(_ids))
    alive: bool = True

    @property
    def pos(self) -> Vector2:
        return Vector2((self.grid[0] + 0.5) * C.TILE, (self.grid[1] + 0.5) * C.TILE)


@dataclass(eq=False)
class Chest(WorldObject):
    """The NPC's stash. `gold` is ground truth; the NPC only has a *belief*."""
    gold: int = 3
    owner_id: int | None = None


@dataclass
class WorldEvent:
    """A one-frame broadcast (e.g. 'theft'). NPCs decide if they saw or heard it."""
    kind: str
    pos: Vector2
    actor: object
    time: float
    data: dict = field(default_factory=dict)


class World:
    def __init__(self, layout: list[str] = LAYOUT, seed: int = C.SEED):
        assert len(layout) == C.GRID_H, "layout height mismatch"
        assert all(len(r) == C.GRID_W for r in layout), "layout width mismatch"
        self.rng = random.Random(seed)
        self.walls = [[ch == "#" for ch in row] for row in layout]
        self.objects: list[WorldObject] = []
        self.entities: list = []          # Player, NPCs, wolves
        self.events: list[WorldEvent] = []
        self.home_tiles: list[tuple[int, int]] = []
        self.spawns: dict[str, tuple[int, int]] = {}
        self.time = 0.0
        self.player = None
        self.chest: Chest | None = None
        for y, row in enumerate(layout):
            for x, ch in enumerate(row):
                if ch == "F":
                    self.objects.append(WorldObject("food", (x, y)))
                elif ch == "$":
                    self.objects.append(WorldObject("coin", (x, y)))
                elif ch == "C":
                    self.chest = Chest("chest", (x, y))
                    self.objects.append(self.chest)
                elif ch == "H":
                    self.home_tiles.append((x, y))
                elif ch in "PN":
                    self.spawns[ch] = (x, y)

    # --- grid helpers ---------------------------------------------------------
    def in_bounds(self, gx: int, gy: int) -> bool:
        return 0 <= gx < C.GRID_W and 0 <= gy < C.GRID_H

    def is_wall(self, gx: int, gy: int) -> bool:
        return not self.in_bounds(gx, gy) or self.walls[gy][gx]

    def is_walkable(self, gx: int, gy: int) -> bool:
        return not self.is_wall(gx, gy)

    @staticmethod
    def tile_center(gx: int, gy: int) -> Vector2:
        return Vector2((gx + 0.5) * C.TILE, (gy + 0.5) * C.TILE)

    @staticmethod
    def to_grid(pos: Vector2) -> tuple[int, int]:
        return int(pos.x // C.TILE), int(pos.y // C.TILE)

    def random_floor(self, near: tuple[int, int] | None = None, radius: int = 6,
                     min_dist: int = 0) -> tuple[int, int]:
        for _ in range(200):
            if near:
                gx = near[0] + self.rng.randint(-radius, radius)
                gy = near[1] + self.rng.randint(-radius, radius)
                if abs(gx - near[0]) + abs(gy - near[1]) < min_dist:
                    continue
            else:
                gx, gy = self.rng.randrange(C.GRID_W), self.rng.randrange(C.GRID_H)
            if self.is_walkable(gx, gy):
                return gx, gy
        return self.spawns["N"]

    # --- raycasting -------------------------------------------------------------
    def raycast(self, start: Vector2, end: Vector2) -> tuple[bool, Vector2]:
        """Amanatides-Woo grid traversal. Returns (blocked, point where the ray stopped)."""
        x0, y0 = start.x / C.TILE, start.y / C.TILE
        x1, y1 = end.x / C.TILE, end.y / C.TILE
        dx, dy = x1 - x0, y1 - y0
        gx, gy = int(x0), int(y0)
        egx, egy = int(x1), int(y1)
        step_x = 1 if dx > 0 else -1
        step_y = 1 if dy > 0 else -1
        t_dx = abs(1 / dx) if dx else math.inf
        t_dy = abs(1 / dy) if dy else math.inf
        t_mx = ((gx + 1 - x0) if dx > 0 else (x0 - gx)) * t_dx if dx else math.inf
        t_my = ((gy + 1 - y0) if dy > 0 else (y0 - gy)) * t_dy if dy else math.inf
        t = 0.0
        while True:
            if self.is_wall(gx, gy):
                return True, start + (end - start) * t
            if (gx, gy) == (egx, egy):
                return False, Vector2(end)
            if t_mx < t_my:
                t, t_mx, gx = t_mx, t_mx + t_dx, gx + step_x
            else:
                t, t_my, gy = t_my, t_my + t_dy, gy + step_y
            if t > 1.0:
                return False, Vector2(end)

    def line_of_sight(self, a: Vector2, b: Vector2) -> bool:
        return not self.raycast(a, b)[0]

    # --- objects & events ---------------------------------------------------------
    def objects_of(self, kind: str) -> list[WorldObject]:
        return [o for o in self.objects if o.alive and o.kind == kind]

    def object_at(self, grid: tuple[int, int], kind: str) -> WorldObject | None:
        for o in self.objects:
            if o.alive and o.kind == kind and o.grid == grid:
                return o
        return None

    def nearest_object(self, pos: Vector2, radius: float, kinds=("food", "coin", "chest")):
        best, best_d = None, radius
        for o in self.objects:
            if o.alive and o.kind in kinds:
                d = o.pos.distance_to(pos)
                if d <= best_d:
                    best, best_d = o, d
        return best

    def remove_object(self, obj: WorldObject) -> None:
        obj.alive = False
        self.objects = [o for o in self.objects if o.alive]

    def spawn_object(self, kind: str, grid: tuple[int, int]) -> WorldObject | None:
        if not self.is_walkable(*grid) or self.object_at(grid, kind):
            return None
        obj = WorldObject(kind, grid)
        self.objects.append(obj)
        return obj

    def emit(self, kind: str, pos: Vector2, actor, **data) -> WorldEvent:
        ev = WorldEvent(kind, Vector2(pos), actor, self.time, data)
        self.events.append(ev)
        return ev

    def end_frame(self) -> None:
        """Events live for exactly one frame; perception must catch them or miss them."""
        self.events.clear()

    # --- rendering -----------------------------------------------------------------
    def draw(self, surf: pygame.Surface, font: pygame.font.Font) -> None:
        T = C.TILE
        for y in range(C.GRID_H):
            for x in range(C.GRID_W):
                r = pygame.Rect(x * T, y * T, T, T)
                if self.walls[y][x]:
                    pygame.draw.rect(surf, C.WALL, r)
                    pygame.draw.rect(surf, C.WALL_TOP, r.inflate(-6, -6).move(0, -2))
                else:
                    pygame.draw.rect(surf, C.FLOOR_A if (x + y) % 2 else C.FLOOR_B, r)
        for gx, gy in self.home_tiles:
            pygame.draw.rect(surf, C.HOME_RUG, (gx * T + 2, gy * T + 2, T - 4, T - 4), border_radius=4)
        for o in self.objects:
            c = o.pos
            if o.kind == "food":
                pygame.draw.circle(surf, C.FOOD_COL, c, 8)
                pygame.draw.line(surf, (90, 200, 90), c + (0, -7), c + (4, -12), 3)
            elif o.kind == "coin":
                pygame.draw.circle(surf, C.COIN_COL, c, 7)
                pygame.draw.circle(surf, (180, 140, 30), c, 7, 2)
            elif isinstance(o, Chest):
                r = pygame.Rect(0, 0, 26, 20)
                r.center = c
                pygame.draw.rect(surf, C.CHEST_COL, r, border_radius=3)
                pygame.draw.rect(surf, C.COIN_COL, r, 2, border_radius=3)
                txt = font.render(str(o.gold), True, C.COIN_COL)
                surf.blit(txt, txt.get_rect(center=(c.x, c.y + 18)))
