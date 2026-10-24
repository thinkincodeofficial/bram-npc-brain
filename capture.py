"""Moment capture for video production.

MomentRecorder.flag() is called from gameplay whenever something worth showing
on camera happens. Each moment is:
  * printed to the console with a video timestamp (time since launch)
  * appended to sessions/<session>/moments.jsonl
  * shown as an on-screen banner if importance >= 2
  * auto-screenshotted if importance >= 3 (after the frame is drawn)
On exit, a human-readable timeline.md is written for the video editor.

Importance scale: 0 = trace, 1 = state change, 2 = notable, 3 = key moment.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pygame

EXPORT_DIR = Path(__file__).resolve().parent  # sessions/ lives next to the code (git-ignored)

BANNER_COLORS = {2: (255, 196, 64), 3: (255, 90, 90)}


@dataclass
class Moment:
    frame: int
    video_time: float       # wall-clock seconds since launch (matches a recording started with the game)
    game_time: float        # simulated seconds (affected by pause / time scale)
    kind: str
    message: str
    importance: int
    actor: str | None = None
    data: dict = field(default_factory=dict)
    screenshot: str | None = None


def fmt_ts(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:06.3f}"


class MomentRecorder:
    def __init__(self, enabled: bool = True, auto_screenshot: bool = True, console_level: int = 1):
        self.enabled = enabled
        self.auto_screenshot = auto_screenshot
        self.console_level = console_level
        self.clock = time.perf_counter   # swap for a frame clock when rendering offline
        self.start = self.clock()
        self.session = time.strftime("%Y%m%d_%H%M%S")
        self.dir = EXPORT_DIR / "sessions" / self.session
        self.moments: list[Moment] = []
        self.banners: list[tuple[str, int, float]] = []   # (text, importance, expires_at)
        self.frame = 0
        self.game_time = 0.0
        self._pending_shots: list[Moment] = []
        self._log = None
        if enabled:
            (self.dir / "screenshots").mkdir(parents=True, exist_ok=True)
            self._log = open(self.dir / "moments.jsonl", "a", encoding="utf-8")

    @property
    def video_time(self) -> float:
        return self.clock() - self.start

    def tick(self, frame: int, game_time: float) -> None:
        self.frame, self.game_time = frame, game_time

    def flag(self, kind: str, message: str, importance: int = 1, actor: str | None = None, **data) -> Moment:
        m = Moment(self.frame, round(self.video_time, 3), round(self.game_time, 3),
                   kind, message, importance, actor, data)
        self.moments.append(m)
        if importance >= self.console_level:
            stars = "*" * importance
            print(f"[{fmt_ts(m.video_time)}] {stars:<3} {kind:<16} {message}")
        if importance >= 2:
            self.banners.append((message, importance, self.video_time + 3.0))
            self.banners = self.banners[-4:]
        if importance >= 3 and self.auto_screenshot and self.enabled:
            self._pending_shots.append(m)
        elif self._log:
            self._write(m)
        return m

    def _write(self, m: Moment) -> None:
        self._log.write(json.dumps(asdict(m)) + "\n")
        self._log.flush()

    def screenshot(self, surface: pygame.Surface, label: str = "manual") -> Path | None:
        if not self.enabled:
            return None
        path = self.dir / "screenshots" / f"{fmt_ts(self.video_time).replace(':', 'm')}_{label}.png"
        pygame.image.save(surface, str(path))
        return path

    def after_render(self, surface: pygame.Surface) -> None:
        """Call once per frame after drawing, so screenshots include overlays + banner."""
        for m in self._pending_shots:
            p = self.screenshot(surface, m.kind)
            m.screenshot = str(p.relative_to(EXPORT_DIR)) if p else None
            self._write(m)
        self._pending_shots.clear()

    def draw_banners(self, surface: pygame.Surface, font: pygame.font.Font, x: int, y: int) -> None:
        now = self.video_time
        self.banners = [b for b in self.banners if b[2] > now]
        for i, (text, imp, exp) in enumerate(reversed(self.banners)):
            alpha = max(0, min(255, int((exp - now) * 255)))
            label = font.render(("KEY MOMENT  " if imp >= 3 else "") + text, True, (15, 15, 20))
            box = pygame.Surface((label.get_width() + 20, label.get_height() + 8), pygame.SRCALPHA)
            box.fill((*BANNER_COLORS.get(imp, (200, 200, 200)), alpha))
            box.blit(label, (10, 4))
            surface.blit(box, (x - box.get_width() // 2, y + i * (box.get_height() + 4)))

    def close(self) -> None:
        if not self.enabled:
            return
        if self._log:
            self._log.close()
        lines = [f"# Session {self.session}", "",
                 "Video timestamps are wall-clock time since the game window opened.", "",
                 "| Video time | Game time | ! | Kind | Moment | Screenshot |",
                 "|---|---|---|---|---|---|"]
        for m in self.moments:
            if m.importance >= 1:
                shot = f"`{m.screenshot}`" if m.screenshot else ""
                lines.append(f"| {fmt_ts(m.video_time)} | {m.game_time:.1f}s | {'*' * m.importance} "
                             f"| {m.kind} | {m.message} | {shot} |")
        (self.dir / "timeline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[capture] {len(self.moments)} moments -> {self.dir}")
