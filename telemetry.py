"""Live telemetry: everything drawn to make the brain *visible* on camera.

World layer (under entities): wall-clipped vision cones, A* paths, memory ghosts
Overhead (above each NPC):    alert icon, speech bubble, action pill, drive bars
Side panel:                   drives, ranked utility scores + 'why' breakdown,
                              memory of the player, stash belief, event log
"""
from __future__ import annotations

import pygame
from pygame.math import Vector2

import config as C
from brain.brain import trust_band

CONE_COLORS = {"flee": (180, 100, 255), "confront": (255, 70, 70), "guard": (255, 110, 90),
               "investigate": (255, 220, 90)}
CONE_DEFAULT = (140, 255, 170)


def _font(size: int, bold: bool = False) -> pygame.font.Font:
    f = pygame.font.SysFont("consolas,menlo,dejavusansmono,couriernew", size, bold=bold)
    return f or pygame.font.Font(None, size + 4)


def lerp_col(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class Telemetry:
    def __init__(self):
        self.f_xs = _font(11)
        self.f_s = _font(12)
        self.f_m = _font(14)
        self.f_b = _font(15, bold=True)
        self.f_title = _font(18, bold=True)
        self.f_icon = _font(30, bold=True)
        self.show_overlay = True    # F1
        self.show_cones = True      # F2
        self.show_paths = True      # F3
        self.show_panel = True      # F4
        self.show_memory = True     # F5
        self.cone_layer = pygame.Surface((C.MAP_W, C.MAP_H), pygame.SRCALPHA)

    # ---------------------------------------------------------------------------------
    def text(self, surf, txt, pos, font=None, color=C.TEXT, center=False):
        img = (font or self.f_m).render(str(txt), True, color)
        r = img.get_rect(center=pos) if center else img.get_rect(topleft=pos)
        surf.blit(img, r)
        return r

    def bar(self, surf, rect, value, color, bg=(40, 44, 54)):
        r = pygame.Rect(rect)
        pygame.draw.rect(surf, bg, r, border_radius=2)
        fill = r.copy()
        fill.width = int(r.width * max(0.0, min(1.0, value)))
        if fill.width:
            pygame.draw.rect(surf, color, fill, border_radius=2)

    # --- world layer -------------------------------------------------------------------
    def draw_world_layer(self, surf, world, npcs):
        if self.show_cones:
            self.cone_layer.fill((0, 0, 0, 0))
            for npc in npcs:
                act = npc.brain.current.name if npc.brain.current else ""
                col = CONE_COLORS.get(act, CONE_DEFAULT)
                pts = npc.brain.perception.cone_polygon(world)
                pygame.draw.polygon(self.cone_layer, (*col, 46), pts)
                pygame.draw.lines(self.cone_layer, (*col, 120), True, pts, 1)
                pygame.draw.circle(self.cone_layer, (*col, 50), npc.pos, int(C.HEARING_RADIUS), 1)
            surf.blit(self.cone_layer, (0, 0))
        if self.show_paths:
            for npc in npcs:
                if npc.path:
                    pts = [npc.pos] + [world.tile_center(*g) for g in npc.path]
                    pygame.draw.lines(surf, (255, 255, 255), False, pts, 1)
                    pygame.draw.circle(surf, (255, 255, 255), pts[-1], 4, 1)
        if self.show_memory:
            for npc in npcs:
                self._draw_memory_ghosts(surf, world, npc)

    def _draw_memory_ghosts(self, surf, world, npc):
        b, now = npc.brain, world.time
        for r in b.memory.resources.values():
            col = C.FOOD_COL if r.kind == "food" else C.COIN_COL
            pygame.draw.circle(surf, col, r.pos, 12, 1)
        for rec in b.memory.entities.values():
            if rec.last_seen_pos is None or b.snapshot.sees(world.player) and rec.kind == "player":
                continue
            age = rec.seconds_since_seen(now)
            if rec.kind == "player" and age < 30:
                p = rec.last_seen_pos
                col = lerp_col(C.DISTRUST_COL, C.TRUST_COL, rec.trust)
                for i in range(0, 360, 30):  # dashed ring = "where I THINK you are"
                    pygame.draw.arc(surf, col, (p.x - 13, p.y - 13, 26, 26),
                                    i * 0.01745, (i + 15) * 0.01745, 2)
                self.text(surf, f"last seen {age:.1f}s", (p.x, p.y + 20), self.f_xs, col, center=True)
        if b.memory.threat_pos is not None and now - b.memory.threat_time < 6:
            p = b.memory.threat_pos
            pygame.draw.line(surf, (255, 80, 80), p + (-7, -7), p + (7, 7), 2)
            pygame.draw.line(surf, (255, 80, 80), p + (-7, 7), p + (7, -7), 2)

    # --- overhead -------------------------------------------------------------------------
    def draw_npc_overlay(self, surf, npc, now: float):
        if not self.show_overlay:
            return
        b = npc.brain
        x, y = npc.pos.x, npc.pos.y - npc.radius - 6
        d = b.drives
        for i, (v, col) in enumerate(((d.hunger, C.HUNGER_COL), (d.fear, C.FEAR_COL), (d.greed, C.GREED_COL))):
            self.bar(surf, (x - 22, y - 12 + i * 4, 44, 3), v, col)
        label = b.current.label if b.current else "..."
        col = b.current.color if b.current else C.TEXT_DIM
        img = self.f_s.render(label, True, (15, 15, 20))
        pill = img.get_rect(midbottom=(x, y - 15)).inflate(10, 4)
        pygame.draw.rect(surf, col, pill, border_radius=8)
        surf.blit(img, img.get_rect(center=pill.center))
        top = pill.top
        if npc.carrying:
            self.text(surf, f"${npc.carrying}", (pill.right + 4, pill.top), self.f_s, C.COIN_COL)
        if npc.alert and now < npc.alert_until:
            icol = (255, 70, 70) if npc.alert == "!" else (255, 220, 90)
            r = self.text(surf, npc.alert, (x, top - 16), self.f_icon, icol, center=True)
            top = r.top
        if npc.speech and now < npc.speech_until:
            img = self.f_m.render(npc.speech, True, (20, 20, 24))
            box = img.get_rect(midbottom=(x, top - 6)).inflate(14, 8)
            box.clamp_ip(pygame.Rect(0, 0, C.MAP_W, C.MAP_H))
            pygame.draw.rect(surf, (245, 245, 240), box, border_radius=6)
            pygame.draw.polygon(surf, (245, 245, 240), [(x - 5, box.bottom), (x + 5, box.bottom), (x, box.bottom + 6)])
            surf.blit(img, img.get_rect(center=box.center))
        self.text(surf, npc.name, (x, npc.pos.y + npc.radius + 8), self.f_xs, C.TEXT, center=True)

    # --- side panel -------------------------------------------------------------------------
    def draw_panel(self, surf, npc, world, controls: list[str]):
        if not self.show_panel:
            return
        x0, w = C.MAP_W, C.PANEL_W
        pygame.draw.rect(surf, C.PANEL_BG, (x0, 0, w, C.SCREEN_H))
        pygame.draw.line(surf, (60, 64, 76), (x0, 0), (x0, C.SCREEN_H), 2)
        x, y = x0 + 12, 8
        b = npc.brain
        self.text(surf, f"NPC BRAIN  //  {npc.name}", (x, y), self.f_title, C.ACCENT)
        y += 26

        y = self._section(surf, "DRIVES", x, y)
        for name, v, col in (("hunger", b.drives.hunger, C.HUNGER_COL), ("fear", b.drives.fear, C.FEAR_COL),
                             ("greed", b.drives.greed, C.GREED_COL)):
            self.text(surf, name, (x, y), self.f_s, C.TEXT_DIM)
            self.bar(surf, (x + 60, y + 3, 200, 9), v, col)
            self.text(surf, f"{v:.2f}", (x + 268, y), self.f_s)
            y += 16
        y += 6

        y = self._section(surf, "UTILITY SCORES  (decision every %.2fs)" % C.DECISION_INTERVAL, x, y)
        for sa in b.scores:
            active = sa.action is b.current
            if active:
                pygame.draw.rect(surf, (40, 46, 60), (x - 4, y - 1, w - 16, 16), border_radius=3)
            self.text(surf, (">" if active else " ") + sa.action.label, (x, y), self.f_s,
                      C.TEXT if active else C.TEXT_DIM)
            self.bar(surf, (x + 130, y + 3, 130, 9), sa.score / 1.3, sa.action.color)
            self.text(surf, f"{sa.score:.2f}" + ("+" if sa.committed else ""), (x + 266, y), self.f_s)
            y += 16
        cur = next((sa for sa in b.scores if sa.action is b.current), None)
        if cur and cur.breakdown:
            why = "  ".join(f"{k} {v:.2f}" for k, v in cur.breakdown.items())
            y = self._wrap(surf, "why: " + why, x, y + 2, w - 24, self.f_xs, C.ACCENT) + 4
        y += 4

        y = self._section(surf, "MEMORY", x, y)
        prec = b.memory.entities.get(world.player.id) if world.player else None
        if prec:
            col = lerp_col(C.DISTRUST_COL, C.TRUST_COL, prec.trust)
            self.text(surf, "trust", (x, y), self.f_s, C.TEXT_DIM)
            self.bar(surf, (x + 60, y + 3, 200, 9), prec.trust, col)
            pygame.draw.line(surf, C.TEXT, (x + 60 + 200 * prec.baseline, y + 1), (x + 60 + 200 * prec.baseline, y + 13))
            self.text(surf, f"{prec.trust:.2f}", (x + 268, y), self.f_s)
            y += 16
            seen = prec.seconds_since_seen(world.time)
            lp = world.to_grid(prec.last_seen_pos) if prec.last_seen_pos else "-"
            for line in (f"player: {trust_band(prec.trust)}   thefts {prec.thefts}   gifts {prec.gifts}",
                         f"last seen {seen:.1f}s ago at {lp}  ({len(prec.sightings)} crumbs)"):
                self.text(surf, line, (x, y), self.f_s)
                y += 15
        else:
            self.text(surf, "player: never seen", (x, y), self.f_s, C.TEXT_DIM)
            y += 15
        belief = b.memory.stash_belief
        self.text(surf, f"stash belief: {belief if belief is not None else '?'} gold   pocket: {npc.carrying}",
                  (x, y), self.f_s)
        y += 15
        self.text(surf, f"knows food x{len(b.memory.known('food'))}   coins x{len(b.memory.known('coin'))}",
                  (x, y), self.f_s)
        y += 21

        y = self._section(surf, "EVENT LOG  (short-term memory)", x, y)
        for t, msg in b.memory.log:
            if y > C.SCREEN_H - 14 * len(controls) - 20:
                break
            self.text(surf, f"{t:6.1f}s {msg}"[:46], (x, y), self.f_xs, C.TEXT_DIM)
            y += 13

        y = C.SCREEN_H - 14 * len(controls) - 8
        pygame.draw.line(surf, (60, 64, 76), (x0 + 8, y - 6), (x0 + w - 8, y - 6))
        for line in controls:
            self.text(surf, line, (x, y), self.f_xs, (110, 116, 130))
            y += 14

    def _section(self, surf, title, x, y):
        self.text(surf, title, (x, y), self.f_b, C.TEXT)
        return y + 19

    def _wrap(self, surf, text, x, y, width, font, color):
        words, line = text.split(" "), ""
        for wd in words:
            trial = (line + " " + wd).strip()
            if font.size(trial)[0] > width and line:
                self.text(surf, line, (x, y), font, color)
                y, line = y + 13, wd
            else:
                line = trial
        if line:
            self.text(surf, line, (x, y), font, color)
            y += 13
        return y

    # --- player HUD --------------------------------------------------------------------------
    def draw_hud(self, surf, player, now, time_scale, paused):
        box = pygame.Surface((230, 44), pygame.SRCALPHA)
        box.fill((10, 12, 16, 170))
        surf.blit(box, (6, 6))
        self.text(surf, f"Coins {player.coins}   Food {player.food}", (14, 10), self.f_b, C.TEXT)
        if player.toast and now - player.toast_time < 2.5:
            self.text(surf, player.toast, (14, 29), self.f_s, C.ACCENT)
        status = ("PAUSED  " if paused else "") + f"x{time_scale:g}  t={now:5.1f}s"
        self.text(surf, status, (C.MAP_W - 10 - self.f_s.size(status)[0], 10), self.f_s,
                  (255, 120, 120) if paused else C.TEXT_DIM)
