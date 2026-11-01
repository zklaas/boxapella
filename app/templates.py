"""Layout templates: where the insets (slots) and reserved regions sit on screen.

A template is a JSON file:

    {"boxapella": 1, "name": "Fourths (2×2)", "description": "...",
     "background": "#111116", "gap": 8, "border": {"width": 0, "color": "#ffffff"},
     "slots":   [{"id": "1", "label": "Top left", "rect": [0, 0, 0.5, 0.5]}, ...],
     "regions": [{"id": "title", "kind": "text", "rect": [0, 0, 1, 0.12],
                  "text": "Title", "fill": "#1d1d28", "color": "#ffffff",
                  "size": 0.06, "align": "center"}]}

rect = [x, y, width, height] as fractions of the screen; later slots are drawn
on top of earlier ones.  gap = pixels (at 1920 wide) left between neighbouring
slots.  A slot may carry its own "border".  Region kinds: "text" (a fill plus
text the project can change) and "color" (a plain fill).
Built-in templates live in templates/; your own go in
~/.config/boxapella/templates/ (Windows: %APPDATA%\\Boxapella\\templates; same
format, same-named files override).
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field

from .config import CONFIG_DIR

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTIN_DIR = os.path.join(HERE, "templates")
USER_DIR = os.path.join(CONFIG_DIR, "templates")


class TemplateError(Exception):
    pass


@dataclass
class Slot:
    id: str
    label: str
    rect: tuple[float, float, float, float]
    border: dict | None = None


@dataclass
class Template:
    name: str
    path: str
    description: str = ""
    background: str = "#111116"
    gap: float = 0.0
    border: dict = field(default_factory=lambda: {"width": 0, "color": "#ffffff"})
    slots: list[Slot] = field(default_factory=list)
    regions: list[dict] = field(default_factory=list)

    @property
    def key(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def slot(self, sid: str) -> Slot | None:
        return next((s for s in self.slots if s.id == sid), None)

    def pixel_rect(self, slot: Slot, w: int, h: int) -> tuple[int, int, int, int]:
        """Slot rectangle in pixels on a w x h screen, gap applied, even sizes."""
        x, y, rw, rh = slot.rect
        g = self.gap * w / 1920 / 2
        x0, y0 = x * w + (g if x > 1e-6 else 0), y * h + (g if y > 1e-6 else 0)
        x1 = (x + rw) * w - (g if x + rw < 1 - 1e-6 else 0)
        y1 = (y + rh) * h - (g if y + rh < 1 - 1e-6 else 0)
        px, py = int(round(x0)), int(round(y0))
        pw, ph = max(2, int(round(x1 - x0)) // 2 * 2), max(2, int(round(y1 - y0)) // 2 * 2)
        return px, py, pw, ph

    def border_of(self, slot: Slot) -> dict:
        return slot.border or self.border or {"width": 0}


def load(path: str) -> Template:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise TemplateError(f"{path}: {e}") from e
    slots = []
    for i, s in enumerate(d.get("slots", [])):
        r = s.get("rect")
        if not (isinstance(r, list) and len(r) == 4):
            raise TemplateError(f"{path}: slot {i + 1} needs rect [x, y, w, h]")
        slots.append(Slot(str(s.get("id", i + 1)), s.get("label", f"Inset {i + 1}"),
                          tuple(float(v) for v in r), s.get("border")))
    if not slots:
        raise TemplateError(f"{path}: no slots")
    return Template(d.get("name", os.path.basename(path)), path, d.get("description", ""),
                    d.get("background", "#111116"), float(d.get("gap", 0)),
                    d.get("border") or {"width": 0, "color": "#ffffff"}, slots,
                    [r for r in d.get("regions", []) if isinstance(r.get("rect"), list)])


def discover() -> list[Template]:
    """Built-in templates, then the user's (a user file overrides a same-named built-in)."""
    by_key: dict[str, Template] = {}
    for folder in (BUILTIN_DIR, USER_DIR):
        for p in sorted(glob.glob(os.path.join(folder, "*.json"))):
            try:
                t = load(p)
            except TemplateError:
                continue
            by_key[t.key] = t
    return sorted(by_key.values(), key=lambda t: t.key)


def find(key_or_name: str) -> Template:
    if os.path.isfile(key_or_name):
        return load(key_or_name)
    for t in discover():
        if key_or_name in (t.key, t.name) or t.name.lower() == key_or_name.lower():
            return t
    raise TemplateError(f"No template called {key_or_name!r} (see `boxapella templates`).")
