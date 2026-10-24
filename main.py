"""Entry point and core game loop.

    python main.py                 # play
    python main.py --no-capture    # don't write sessions/ files
    python main.py --frames 600    # auto-quit after N frames (smoke tests)
"""
from __future__ import annotations

import argparse

import pygame

import config as C
from capture import MomentRecorder
from entities import Player, Wolf
from npc import NPC
from telemetry import Telemetry
from world import World

CONTROLS = [
    "WASD move   E steal/pick up   G give food",
    "T spawn wolf   F/C drop food/coin at mouse",
    "F1 overlay F2 cones F3 paths F4 panel F5 memory",
    "SPACE pause  [ ] speed  F9 mark  F12 screenshot",
]


class Game:
    def __init__(self, capture: bool = True, seed: int = C.SEED):
        pygame.init()
        self.screen = pygame.display.set_mode((C.SCREEN_W, C.SCREEN_H))
        pygame.display.set_caption("NPC Brain - Utility AI, Memory & Perception")
        self.clock = pygame.time.Clock()
        self.recorder = MomentRecorder(enabled=capture)
        self.telemetry = Telemetry()

        self.world = World(seed=seed)
        self.player = Player(self.world.spawns["P"])
        self.npc = NPC("Bram", self.world.spawns["N"], self.recorder)
        self.npcs = [self.npc]
        self.wolves: list[Wolf] = []
        self.world.player = self.player
        self.world.chest.owner_id = self.npc.id
        self.world.entities += [self.player, *self.npcs]

        self.paused = False
        self.scale_idx = C.TIME_SCALES.index(1.0)
        self.frame = 0
        self.running = True
        self.recorder.flag("session_start", f"Session started (seed {seed})", importance=1)

    @property
    def time_scale(self) -> float:
        return C.TIME_SCALES[self.scale_idx]

    def mouse_grid(self) -> tuple[int, int] | None:
        mx, my = pygame.mouse.get_pos()
        return (mx // C.TILE, my // C.TILE) if mx < C.MAP_W else None

    def spawn_wolf(self) -> None:
        grid = self.world.random_floor(self.npc.grid, 12, min_dist=8)
        wolf = Wolf(grid)
        self.wolves.append(wolf)
        self.world.entities.append(wolf)
        self.recorder.flag("wolf_spawn", f"A wolf appeared at {grid}", importance=2)

    # --- input ---------------------------------------------------------------------------
    def handle_event(self, e: pygame.event.Event) -> None:
        if e.type == pygame.QUIT:
            self.running = False
        if e.type != pygame.KEYDOWN:
            return
        k, tel, w = e.key, self.telemetry, self.world
        if k == pygame.K_ESCAPE:
            self.running = False
        elif k == pygame.K_e:
            self.player.interact(w, self.recorder)
        elif k == pygame.K_g:
            self.player.give_food(w, self.npcs, self.recorder)
        elif k == pygame.K_t:
            self.spawn_wolf()
        elif k in (pygame.K_f, pygame.K_c) and (g := self.mouse_grid()):
            kind = "food" if k == pygame.K_f else "coin"
            if w.spawn_object(kind, g):
                self.recorder.flag("spawn", f"Director dropped {kind} at {g}", importance=1)
        elif k == pygame.K_F1:
            tel.show_overlay = not tel.show_overlay
        elif k == pygame.K_F2:
            tel.show_cones = not tel.show_cones
        elif k == pygame.K_F3:
            tel.show_paths = not tel.show_paths
        elif k == pygame.K_F4:
            tel.show_panel = not tel.show_panel
        elif k == pygame.K_F5:
            tel.show_memory = not tel.show_memory
        elif k == pygame.K_F9:
            self.recorder.flag("director_mark", "Manual marker (F9)", importance=3)
        elif k == pygame.K_F12:
            p = self.recorder.screenshot(self.screen)
            if p:
                print(f"[capture] screenshot -> {p}")
        elif k == pygame.K_SPACE:
            self.paused = not self.paused
        elif k == pygame.K_LEFTBRACKET:
            self.scale_idx = max(0, self.scale_idx - 1)
        elif k == pygame.K_RIGHTBRACKET:
            self.scale_idx = min(len(C.TIME_SCALES) - 1, self.scale_idx + 1)

    # --- simulation ------------------------------------------------------------------------
    def update(self, dt: float) -> None:
        if self.paused:
            return
        dt *= self.time_scale
        w = self.world
        w.time += dt
        self.recorder.tick(self.frame, w.time)
        self.player.handle_movement(pygame.key.get_pressed(), w, dt)
        for npc in self.npcs:
            npc.update(w, dt)
        for wolf in self.wolves:
            wolf.update(w, self.npcs, dt, self.recorder)
        self.wolves = [x for x in self.wolves if x.alive]
        w.entities = [x for x in w.entities if x.alive]
        w.end_frame()

    # --- rendering ---------------------------------------------------------------------------
    def draw(self) -> None:
        s, tel, w = self.screen, self.telemetry, self.world
        s.fill(C.BG)
        w.draw(s, tel.f_s)
        tel.draw_world_layer(s, w, self.npcs)
        for ent in w.entities:
            ent.draw(s)
        for npc in self.npcs:
            tel.draw_npc_overlay(s, npc, w.time)
        tel.draw_hud(s, self.player, w.time, self.time_scale, self.paused)
        self.recorder.draw_banners(s, tel.f_m, C.MAP_W // 2, C.MAP_H - 124)
        tel.draw_panel(s, self.npc, w, CONTROLS)
        self.recorder.after_render(s)
        pygame.display.flip()

    def run(self, max_frames: int | None = None) -> None:
        try:
            while self.running:
                dt = min(self.clock.tick(C.FPS) / 1000.0, C.MAX_DT)
                for e in pygame.event.get():
                    self.handle_event(e)
                self.update(dt)
                self.draw()
                self.frame += 1
                if max_frames and self.frame >= max_frames:
                    break
        finally:
            self.recorder.close()
            pygame.quit()


def main() -> None:
    ap = argparse.ArgumentParser(description="NPC Brain demo")
    ap.add_argument("--no-capture", action="store_true", help="don't write moments/screenshots")
    ap.add_argument("--frames", type=int, default=None, help="quit after N frames")
    ap.add_argument("--seed", type=int, default=C.SEED)
    args = ap.parse_args()
    Game(capture=not args.no_capture, seed=args.seed).run(args.frames)


if __name__ == "__main__":
    main()
