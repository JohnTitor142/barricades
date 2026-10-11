"""Aperçu d'une carte en PNG, sans lancer le jeu : zones, murs, portes, obstacles, meubles, apparitions.

    python tools/render_map.py ville                 # -> ville.png
    python tools/render_map.py ville --nav out.png   # + cases infranchissables pour les bots (en rouge)

Sert à relire une carte générée à partir d'une description avant de la jouer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.game import Settings, World

GROUND = {
    "floor": (42, 32, 24), "wood": (58, 42, 28), "tile": (52, 56, 60), "carpet": (60, 30, 38),
    "stone": (58, 57, 54), "straw": (78, 66, 34), "concrete": (48, 48, 48), "grass": (30, 44, 24),
    "asphalt": (30, 30, 32), "sidewalk": (70, 68, 64), "dirt": (66, 50, 32), "field": (52, 62, 28),
    "gravel": (64, 62, 56), "cemetery": (34, 40, 32),
}
WALL = {
    "brick": (120, 66, 52), "wood": (110, 82, 52), "stone": (120, 118, 110), "concrete": (90, 88, 84),
    "fence": (130, 105, 70), "iron": (106, 106, 114), "hedge": (34, 70, 30), "grave": (130, 130, 136),
}
OBSTACLE = {"tree": (28, 60, 26), "rock": (90, 88, 84), "well": (80, 80, 90), "silo": (150, 150, 150),
            "pillar": (90, 88, 84), "pump": (170, 40, 40)}


def render(name: str, out: Path, nav: bool, width: int = 1800) -> Path:
    w = World(Settings(map=name), seed=7)
    m = w.map
    k = width / m.w
    img = Image.new("RGB", (width, int(m.h * k)), GROUND.get(m.base, (40, 40, 40)))
    d = ImageDraw.Draw(img, "RGBA")
    P = lambda x, y: (x * k, y * k)

    for a in m.areas:
        d.polygon([P(*p) for p in a.poly], fill=GROUND.get(a.ground, (80, 0, 80)))
    if nav:
        c = w.nav.cell * k
        for i, j in zip(*w.nav.blocked.nonzero(), strict=True):
            d.rectangle([i * c, j * c, (i + 1) * c, (j + 1) * c], fill=(255, 0, 0, 55))
    for wl in m.walls:
        col, r = WALL.get(wl.style, (200, 0, 200)), wl.t / 2 * k
        d.line([P(wl.x1, wl.y1), P(wl.x2, wl.y2)], fill=col, width=max(1, round(wl.t * k)))
        for x, y in ((wl.x1, wl.y1), (wl.x2, wl.y2)):
            d.ellipse([x * k - r, y * k - r, x * k + r, y * k + r], fill=col)
    for ob in m.obstacles:
        x, y = P(ob.x, ob.y)
        d.ellipse([x - ob.r * k, y - ob.r * k, x + ob.r * k, y + ob.r * k], fill=OBSTACLE.get(ob.kind, (200, 0, 200)))
    for pr in w.props.values():
        for sh in pr.shapes:
            if hasattr(sh, "get_vertices"):
                pts = [P(*pr.body.local_to_world(v)) for v in sh.get_vertices()]
                d.polygon(pts, fill=(150, 110, 70), outline=(0, 0, 0))
            else:
                x, y = P(*pr.body.local_to_world(sh.offset))
                d.ellipse([x - sh.radius * k, y - sh.radius * k, x + sh.radius * k, y + sh.radius * k],
                          fill=(150, 110, 70), outline=(0, 0, 0))
    for a in m.areas:
        if a.spawn:
            col = (230, 60, 60, 255) if a.spawn == "zombie" else (90, 220, 120, 255)
            d.line([P(*p) for p in (*a.poly, a.poly[0])], fill=col, width=3)
        x, y = P(*a.inner_point())
        d.text((x - 3 * len(a.id), y - 5), a.id, fill=(235, 235, 220, 200))
    for x, y in m.doors:
        cx, cy = P(x, y)
        d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 220, 0))
    for x, y in m.unused_doors:
        cx, cy = P(x, y)
        d.rectangle([cx - 7, cy - 7, cx + 7, cy + 7], outline=(255, 0, 255), width=3)
    img.save(out)
    print(f"{out} : {len(m.areas)} zones, {len(m.walls)} murs, {len(m.doors)} portes "
          f"({len(m.unused_doors)} inutilisée(s)), {len(m.obstacles)} obstacles, {len(w.props)} meubles")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("map")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--nav", action="store_true", help="affiche la grille de navigation des bots")
    ap.add_argument("--width", type=int, default=1800)
    args = ap.parse_args()
    render(args.map, Path(args.out or f"{args.map}.png"), args.nav, args.width)
