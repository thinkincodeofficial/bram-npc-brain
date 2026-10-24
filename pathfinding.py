"""A* over the tile grid (8-directional, no corner cutting)."""
from __future__ import annotations

import heapq
import math

DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def octile(a: tuple[int, int], b: tuple[int, int]) -> float:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)


def astar(world, start: tuple[int, int], goal: tuple[int, int],
          max_nodes: int = 5000) -> list[tuple[int, int]] | None:
    """Returns the tile path from start to goal (inclusive), or None if unreachable."""
    if not world.is_walkable(*goal):
        return None
    if start == goal:
        return [start]
    open_heap = [(octile(start, goal), 0, start)]
    g = {start: 0.0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    tie = 0
    expanded = 0
    while open_heap and expanded < max_nodes:
        _, _, cur = heapq.heappop(open_heap)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        expanded += 1
        for dx, dy in DIRS:
            nx, ny = cur[0] + dx, cur[1] + dy
            if not world.is_walkable(nx, ny):
                continue
            if dx and dy and not (world.is_walkable(cur[0] + dx, cur[1]) and
                                  world.is_walkable(cur[0], cur[1] + dy)):
                continue  # don't clip wall corners
            ng = g[cur] + (1.4142 if dx and dy else 1.0)
            if ng < g.get((nx, ny), math.inf):
                g[(nx, ny)] = ng
                came[(nx, ny)] = cur
                tie += 1
                heapq.heappush(open_heap, (ng + octile((nx, ny), goal), tie, (nx, ny)))
    return None
