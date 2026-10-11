"""Cartes : uniquement des données (murs, portes, pièces). Aucune règle de jeu ici.

Une carte = un rectangle w x h entouré de murs, des murs intérieurs (avec des portes = trous),
des piliers éventuels, et des « pièces » (rectangles) qui servent aux apparitions et au placement
des meubles. La pièce `zombie_room` est celle où apparaissent les zombies.
"""
from __future__ import annotations

from dataclasses import dataclass

WALL_T = 30.0
DOOR_W = 120.0

Rect = tuple[float, float, float, float]          # (x0, y0, x1, y1)
Wall = tuple[float, float, float, float]          # (cx, cy, w, h)


@dataclass(frozen=True)
class MapDef:
    name: str
    w: float
    h: float
    walls: list[Wall]                 # tous les murs, bordure comprise
    doors: list[tuple[float, float]]  # centres des portes
    rooms: list[Rect]
    zombie_room: int


class _Builder:
    def __init__(self, w: float, h: float) -> None:
        t = WALL_T
        self.w, self.h = w, h
        self.walls: list[Wall] = [
            (w / 2, -t / 2, w + 2 * t, t), (w / 2, h + t / 2, w + 2 * t, t),
            (-t / 2, h / 2, t, h), (w + t / 2, h / 2, t, h),
        ]
        self.doors: list[tuple[float, float]] = []

    @staticmethod
    def _spans(a: float, b: float, doors: list[float]) -> list[tuple[float, float]]:
        out, cur = [], a
        for c in sorted(doors):
            lo, hi = c - DOOR_W / 2, c + DOOR_W / 2
            if lo > cur:
                out.append((cur, lo))
            cur = hi
        if cur < b:
            out.append((cur, b))
        return out

    def vwall(self, x: float, y0: float, y1: float, doors: list[float]) -> None:
        """Mur vertical en x, de y0 à y1, percé de portes centrées sur `doors` (y)."""
        for a, b in self._spans(y0, y1, doors):
            self.walls.append((x, (a + b) / 2, WALL_T, b - a))
        self.doors += [(x, y) for y in doors]

    def hwall(self, y: float, x0: float, x1: float, doors: list[float]) -> None:
        """Mur horizontal en y, de x0 à x1, percé de portes centrées sur `doors` (x)."""
        for a, b in self._spans(x0, x1, doors):
            self.walls.append(((a + b) / 2, y, b - a, WALL_T))
        self.doors += [(x, y) for x in doors]

    def pillar(self, cx: float, cy: float, size: float) -> None:
        self.walls.append((cx, cy, size, size))

    def build(self, name: str, rooms: list[Rect], zombie_room: int) -> MapDef:
        return MapDef(name, self.w, self.h, self.walls, self.doors, rooms, zombie_room)


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
    b.vwall(600, 0, 1200, [200, 1000])                   # sorties de la salle des zombies (coins)
    b.vwall(1300, 0, 1200, [200, 600])
    b.vwall(2000, 0, 1200, [600, 1000])
    b.vwall(2700, 0, 1200, [200, 600])
    b.vwall(3400, 0, 1200, [600, 1000])                  # entrées de la salle finale
    b.hwall(400, 600, 3400, [950, 2350, 3050])           # rangée du haut / couloir central
    b.hwall(800, 600, 3400, [950, 1650, 3050])           # couloir central / rangée du bas
    for cx, cy in [(3700, 330), (3700, 870), (3560, 600)]:
        b.pillar(cx, cy, 90)
    cols, rows = [600, 1300, 2000, 2700, 3400], [0, 400, 800, 1200]
    rooms: list[Rect] = [(0, 0, 600, 1200)]              # 0 : salle des zombies
    rooms += [(cols[c], rows[r], cols[c + 1], rows[r + 1]) for r in range(3) for c in range(4)]
    rooms.append((3400, 0, 4000, 1200))                  # salle finale
    return b.build("entrepot", rooms, zombie_room=0)


MAPS = {"manoir": manoir, "entrepot": entrepot}


def get_map(name: str) -> MapDef:
    try:
        return MAPS[name]()
    except KeyError:
        raise ValueError(f"carte inconnue : {name!r} (disponibles : {', '.join(MAPS)})") from None
