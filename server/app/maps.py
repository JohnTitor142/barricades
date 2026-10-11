"""Cartes : uniquement des données (zones, murs, portes, obstacles). Aucune règle de jeu ici.

Une carte se décrit dans un fichier JSON (app/map_data/<nom>.json), pensé pour être écrit à partir d'une
description en langage naturel, sans rien régler à la main pour la physique ni la navigation :

- areas     : polygones (ou rectangles) qui donnent le SOL (« ground »), un THÈME de mobilier (« theme ») et
              éventuellement un rôle d'apparition (« spawn » : "human" ou "zombie").
- walls     : lignes brisées de murs, à n'importe quel angle (« path », « closed », épaisseur « t », « style »).
- doors     : simples points [x, y] (ou [x, y, largeur]) : le mur qui passe là est percé automatiquement.
- obstacles : fixes et indestructibles : cercles (arbre, rocher, puits, silo, pilier, pompe) ou « grave »
              (tombe : petit bloc orienté).
- props     : meubles posés à un endroit précis (voiture dans la rue, benne...) en plus du mobilier par thème.

La bordure de la carte est ajoutée automatiquement. Voir app/map_data/README.md pour le format complet.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

WALL_T = 30.0
DOOR_W = 110.0
DATA_DIR = Path(__file__).with_name("map_data")

Point = tuple[float, float]


@dataclass(frozen=True)
class Area:
    id: str
    poly: tuple[Point, ...]
    ground: str = "floor"
    theme: str | None = None          # mobilier posé automatiquement (voir THEMES dans game.py)
    spawn: str | None = None          # "human" | "zombie" | None

    def contains(self, x: float, y: float) -> bool:
        """Point dans le polygone (règle pair-impair)."""
        inside = False
        pts = self.poly
        j = len(pts) - 1
        for i in range(len(pts)):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs, ys = [p[0] for p in self.poly], [p[1] for p in self.poly]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def surface(self) -> float:
        pts = self.poly
        return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2

    def random_point(self, rng: random.Random, margin: float = 0.0, tries: int = 200) -> Point | None:
        """Point tiré au hasard dans la zone, à `margin` px au moins de ses bords (None si introuvable)."""
        x0, y0, x1, y1 = self.bbox
        for _ in range(tries):
            x, y = rng.uniform(x0 + margin, x1 - margin), rng.uniform(y0 + margin, y1 - margin)
            if self.contains(x, y) and (margin <= 0 or self.edge_distance(x, y) >= margin):
                return x, y
        return None

    def inner_point(self) -> Point:
        """Un point sûr à l'intérieur (zone concave comprise), déterministe : tests et outils."""
        x0, y0, x1, y1 = self.bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if self.contains(cx, cy):
            return cx, cy
        return self.random_point(random.Random(0)) or (cx, cy)

    def edge_distance(self, x: float, y: float) -> float:
        pts = self.poly
        return min(_seg_dist(x, y, *pts[i - 1], *pts[i]) for i in range(len(pts)))


@dataclass(frozen=True)
class Wall:
    x1: float
    y1: float
    x2: float
    y2: float
    t: float = WALL_T
    style: str = "brick"

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


@dataclass(frozen=True)
class Obstacle:
    """Obstacle rond, fixe et indestructible (arbre, rocher, puits...)."""
    kind: str
    x: float
    y: float
    r: float


@dataclass(frozen=True)
class FixedProp:
    kind: str
    x: float
    y: float
    angle: float = 0.0                # radians


@dataclass(frozen=True)
class MapDef:
    name: str
    w: float
    h: float
    areas: list[Area]
    walls: list[Wall]
    doors: list[Point]
    obstacles: list[Obstacle] = field(default_factory=list)
    props: list[FixedProp] = field(default_factory=list)
    base: str = "floor"                # sol par défaut, sous toutes les zones
    unused_doors: list[Point] = field(default_factory=list)   # portes qui ne percent aucun mur (erreur d'auteur)

    def areas_for(self, spawn: str) -> list[int]:
        return [i for i, a in enumerate(self.areas) if a.spawn == spawn]

    @property
    def zombie_areas(self) -> list[int]:
        return self.areas_for("zombie")

    @property
    def human_areas(self) -> list[int]:
        return self.areas_for("human")


# ----------------------------------------------------------------- géométrie
def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    k = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + k * dx), py - (ay + k * dy))


def cut_doors(segments: list[tuple[Point, Point, float, str]], doors: list[tuple[float, float, float]]
              ) -> tuple[list[Wall], list[Point]]:
    """Perce les murs aux portes : l'ouverture laissée fait exactement la largeur demandée (les murs ont des
    extrémités arrondies de rayon t/2, on retire donc t/2 de plus de chaque côté)."""
    used = [False] * len(doors)
    walls: list[Wall] = []
    for (ax, ay), (bx, by), t, style in segments:
        L = math.hypot(bx - ax, by - ay)
        if L < 1e-6:
            continue
        ux, uy = (bx - ax) / L, (by - ay) / L
        cuts = []
        for k, (dx, dy, dw) in enumerate(doors):
            s = (dx - ax) * ux + (dy - ay) * uy
            perp = abs((dx - ax) * uy - (dy - ay) * ux)
            if -dw / 2 < s < L + dw / 2 and perp <= t / 2 + 8:
                cuts.append((s - dw / 2 - t / 2, s + dw / 2 + t / 2))
                used[k] = True
        cur = 0.0
        for a, b in sorted(cuts) + [(L, L)]:
            if a > cur + 1:
                walls.append(Wall(ax + ux * cur, ay + uy * cur, ax + ux * a, ay + uy * a, t, style))
            cur = max(cur, b)
    return walls, [(d[0], d[1]) for d, u in zip(doors, used, strict=True) if not u]


def _rect_poly(x0: float, y0: float, x1: float, y1: float) -> tuple[Point, ...]:
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def _border(w: float, h: float, t: float = WALL_T) -> list[tuple[Point, Point, float, str]]:
    """Bordure de carte : le mur est tout entier à l'extérieur."""
    o = t / 2
    pts = [(-o, -o), (w + o, -o), (w + o, h + o), (-o, h + o)]
    return [(pts[i], pts[(i + 1) % 4], t, "concrete") for i in range(4)]


# ------------------------------------------------------------ cartes en JSON
def _poly_of(spec: dict) -> tuple[Point, ...]:
    if "rect" in spec:
        return _rect_poly(*spec["rect"])
    return tuple((float(x), float(y)) for x, y in spec["poly"])


def load_json(path: Path) -> MapDef:
    d = json.loads(path.read_text(encoding="utf-8"))
    w, h = map(float, d["size"])
    areas = [Area(a["id"], _poly_of(a), a.get("ground", "floor"), a.get("theme"), a.get("spawn"))
             for a in d.get("areas", [])]
    segs: list[tuple[Point, Point, float, str]] = _border(w, h)
    for wl in d.get("walls", []):
        pts = list(_rect_poly(*wl["rect"])) if "rect" in wl else [tuple(p) for p in wl["path"]]
        closed = wl.get("closed", "rect" in wl)
        t, style = float(wl.get("t", 24)), wl.get("style", "brick")
        n = len(pts) if closed else len(pts) - 1
        segs += [(pts[i], pts[(i + 1) % len(pts)], t, style) for i in range(n)]
    obstacles: list[Obstacle] = []
    for ob in d.get("obstacles", []):
        if ob["kind"] == "grave":                          # tombe : petit bloc orienté = mur court
            (cx, cy), (bw, bh) = ob["at"], ob.get("size", (34, 18))
            a = math.radians(ob.get("angle", 0))
            long_, short = (bw, bh) if bw >= bh else (bh, bw)
            ux, uy = (math.cos(a), math.sin(a)) if bw >= bh else (-math.sin(a), math.cos(a))
            half = (long_ - short) / 2
            segs.append(((cx - ux * half, cy - uy * half), (cx + ux * half, cy + uy * half), short, "grave"))
        else:
            obstacles.append(Obstacle(ob["kind"], float(ob["at"][0]), float(ob["at"][1]), float(ob.get("r", 30))))
    doors = [(float(dd[0]), float(dd[1]), float(dd[2]) if len(dd) > 2 else DOOR_W) for dd in d.get("doors", [])]
    walls, unused = cut_doors(segs, doors)
    props = [FixedProp(p["kind"], float(p["at"][0]), float(p["at"][1]), math.radians(p.get("angle", 0)))
             for p in d.get("props", [])]
    return MapDef(d["name"], w, h, areas, walls, [(dd[0], dd[1]) for dd in doors], obstacles, props,
                  d.get("base", "floor"), unused)


# ------------------------------------------------------- cartes historiques
class _Builder:
    """Cartes d'origine (grilles de pièces rectangulaires), exprimées dans le format générique."""

    def __init__(self, w: float, h: float) -> None:
        self.w, self.h = w, h
        self.segs = _border(w, h)
        self.doors: list[tuple[float, float, float]] = []
        self.obstacles: list[Obstacle] = []

    def vwall(self, x: float, y0: float, y1: float, doors: list[float]) -> None:
        self.segs.append(((x, y0), (x, y1), WALL_T, "concrete"))
        self.doors += [(x, y, 120.0) for y in doors]

    def hwall(self, y: float, x0: float, x1: float, doors: list[float]) -> None:
        self.segs.append(((x0, y), (x1, y), WALL_T, "concrete"))
        self.doors += [(x, y, 120.0) for x in doors]

    def pillar(self, cx: float, cy: float, size: float) -> None:
        self.obstacles.append(Obstacle("pillar", cx, cy, size / 2))

    def build(self, name: str, rooms: list[tuple[float, float, float, float]], zombie_room: int) -> MapDef:
        walls, unused = cut_doors(self.segs, self.doors)
        areas = [Area(f"piece{i}", _rect_poly(*r), "floor", "mixed", "zombie" if i == zombie_room else "human")
                 for i, r in enumerate(rooms)]
        return MapDef(name, self.w, self.h, areas, walls, [(d[0], d[1]) for d in self.doors],
                      self.obstacles, [], "floor", unused)


def manoir() -> MapDef:
    """Carte d'origine : 6 pièces de 800 x 800 (3 colonnes x 2 lignes)."""
    b = _Builder(2400, 1600)
    b.vwall(800, 0, 1600, [360, 1160])
    b.vwall(1600, 0, 1600, [560, 1060])
    b.hwall(800, 0, 2400, [360, 1060, 1960])
    cols, rows = [0, 800, 1600, 2400], [0, 800, 1600]
    rooms = [(cols[c], rows[r], cols[c + 1], rows[r + 1]) for r in range(2) for c in range(3)]
    return b.build("manoir", rooms, zombie_room=2)


def entrepot() -> MapDef:
    """Carte en longueur : salle des zombies à gauche, 3 rangées de pièces étroites au centre,
    grande salle finale à droite (une seule entrée centrale + une latérale, piliers pour se couvrir)."""
    b = _Builder(4000, 1200)
    b.vwall(600, 0, 1200, [200, 1000])
    b.vwall(1300, 0, 1200, [200, 600])
    b.vwall(2000, 0, 1200, [600, 1000])
    b.vwall(2700, 0, 1200, [200, 600])
    b.vwall(3400, 0, 1200, [600, 1000])
    b.hwall(400, 600, 3400, [950, 2350, 3050])
    b.hwall(800, 600, 3400, [950, 1650, 3050])
    for cx, cy in [(3700, 330), (3700, 870), (3560, 600)]:
        b.pillar(cx, cy, 90)
    cols, rows = [600, 1300, 2000, 2700, 3400], [0, 400, 800, 1200]
    rooms = [(0.0, 0.0, 600.0, 1200.0)]
    rooms += [(cols[c], rows[r], cols[c + 1], rows[r + 1]) for r in range(3) for c in range(4)]
    rooms.append((3400, 0, 4000, 1200))
    return b.build("entrepot", rooms, zombie_room=0)


def available() -> list[str]:
    return sorted({"manoir", "entrepot", *(p.stem for p in DATA_DIR.glob("*.json"))})


MAPS = available()


def get_map(name: str) -> MapDef:
    if name == "manoir":
        return manoir()
    if name == "entrepot":
        return entrepot()
    path = DATA_DIR / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"carte inconnue : {name!r} (disponibles : {', '.join(available())})")
    return load_json(path)
