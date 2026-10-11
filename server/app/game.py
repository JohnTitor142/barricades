"""Barricade : logique de jeu (vue de dessus, physique 2D pymunk).

Aucun I/O ici : le module est pur, donc testable sans réseau.

Règles
------
- Une manche : un joueur tiré au hasard devient « patient zéro » (zombie),
  figé quelques secondes pour laisser les humains se barricader.
- Un zombie qui touche un humain l'infecte. Les humains gagnent si le timer
  arrive à zéro, les zombies si plus aucun humain ne reste.
- Tout le monde peut *frapper* (les objets glissent, les joueurs reculent).
  Les coups de ZOMBIE abîment les meubles (20 à 50 coups) ; à 0 PV le meuble casse (débloque une barricade)
  et revient à la manche suivante. Les humains et les balles poussent sans abîmer.
- Les humains ont un pistolet : un tir pousse les objets et ralentit les zombies.
- Les zombies ont beaucoup de PV : balles et coups des humains finissent par les abattre ;
  ils réapparaissent alors dans leur salle après quelques secondes (invulnérables pendant l'attente).
- Le serveur fait autorité sur tout (positions, tirs, infection).
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field

import numpy as np
import pymunk
import tcod.path
from pymunk import ShapeFilter

from .maps import MapDef, Obstacle, Wall, get_map

TICK_RATE = 30
# À incrémenter à chaque changement du protocole : un client d'une autre version se recharge tout seul.
PROTOCOL_VERSION = 5
SUBSTEPS = 2                       # pas de physique par tick (60 Hz)

# --- Monde (les cartes elles-mêmes sont dans maps.py) ----------------------
GROUND_DAMPING = 0.05              # fraction de vitesse conservée après 1 s (frottement au sol)

# --- Joueurs -------------------------------------------------------------
PLAYER_R = 16.0
PLAYER_MASS = 5.0
DRIVE_FORCE = 10000.0              # force max du « moteur » du joueur : accélère vite à vide, mais ne déplace pas un meuble
HUMAN_SPEED = 200.0
ZOMBIE_SPEED = 215.0
SLOW_FACTOR = 0.45
SLOW_TIME = 1.5
INFECT_DIST = 2 * PLAYER_R + 2
INFECT_STUN = 1.0                  # le nouveau zombie est figé un instant
KNOCKBACK_DECAY = 6.0

# --- Bots ------------------------------------------------------------------
NAV_CELL = 40.0
NAV_MARGIN = PLAYER_R + 10         # une case de navigation est « libre » si un joueur y tient avec de la marge
FLOW_REFRESH = 0.25                # s entre deux recalculs de la carte des distances vers les humains
FLOW_LOOKAHEAD = 8                 # cases suivies le long de la pente pour couper les virages (si la voie est libre)
UNREACHABLE = int(np.iinfo(np.int32).max)
BOT_REPLAN = (0.1, 0.2)            # s entre deux choix de cap d'un bot (aléatoire : on étale les calculs entre bots)

# --- Frappe (tout le monde) ------------------------------------------------
HIT_COOLDOWN = 0.45
HIT_IMPULSE = 3500.0               # chaise (6) -> ~580 px/s ; armoire (60) -> ~58 px/s
HIT_REACH = 62.0
HIT_RADIUS = 34.0
KNOCKBACK = 260.0

# --- Pistolet (humains) ----------------------------------------------------
SHOT_COOLDOWN = 0.35
SHOT_RANGE = 900.0
SHOT_IMPULSE = 1800.0
MAG_SIZE = 6
RELOAD_TIME = 2.0
SHOT_KNOCKBACK = 140.0

# --- Points de vie des zombies -----------------------------------------------
ZOMBIE_HP = 300                    # mesuré à 24 bots : à 100 PV le patient zéro était abattu en boucle à la sortie
BULLET_DAMAGE = 10                 # de sa salle ; à 300, ~4 zombies abattus/manche ; à 500+, plus aucun (30 balles = 5 chargeurs)
MELEE_DAMAGE = 20                  # 15 coups, mais au contact = risque d'infection
RESPAWN_TIME = 5.0

HUMAN, ZOMBIE = 0, 1
CAT_WALL, CAT_PROP, CAT_HUMAN, CAT_ZOMBIE = 1, 2, 4, 8
ALL_SOLID = CAT_WALL | CAT_PROP | CAT_HUMAN | CAT_ZOMBIE
HIT_FILTER = ShapeFilter(mask=CAT_PROP | CAT_HUMAN | CAT_ZOMBIE)
SHOT_FILTER = ShapeFilter(mask=CAT_WALL | CAT_PROP | CAT_ZOMBIE)   # pas de tir ami
WALL_ONLY = ShapeFilter(mask=CAT_WALL)

# Les meubles sont ~20x plus massifs que les joueurs : marcher dessus ne les déplace pas,
# il faut les FRAPPER ou leur tirer dessus. Les impulsions sont mises à l'échelle en conséquence,
# donc les vitesses obtenues (voir HIT_IMPULSE) restent celles d'une masse « nominale ».
MASS_SCALE = 20.0



@dataclass(frozen=True)
class PropKind:
    """Un type de meuble : une ou plusieurs formes CONVEXES solidaires (repère local, centre = (0, 0)).
    ("box", largeur, hauteur, dx, dy) | ("circle", rayon, dx, dy) | ("poly", ((x, y), ...)).
    hp = nombre de COUPS DE ZOMBIE pour le casser (les humains et les balles poussent sans abîmer)."""
    parts: tuple
    mass: float                    # masse « nominale » (voir MASS_SCALE)
    hp: int

    @property
    def radius(self) -> float:
        """Rayon du cercle englobant (placement en début de manche)."""
        r = 0.0
        for part in self.parts:
            if part[0] == "box":
                _, w, h, dx, dy = part
                r = max(r, math.hypot(abs(dx) + w / 2, abs(dy) + h / 2))
            elif part[0] == "circle":
                _, rad, dx, dy = part
                r = max(r, math.hypot(dx, dy) + rad)
            else:
                r = max(r, *(math.hypot(x, y) for x, y in part[1]))
        return r


PROP_KINDS: dict[str, PropKind] = {
    "chair": PropKind((("box", 30, 30, 0, 0),), 6, 20),
    "barrel": PropKind((("circle", 22, 0, 0),), 14, 25),
    "crate": PropKind((("box", 52, 52, 0, 0),), 12, 25),
    "table": PropKind((("box", 110, 64, 0, 0),), 25, 30),
    "round_table": PropKind((("circle", 44, 0, 0),), 25, 30),
    "bookshelf": PropKind((("box", 150, 32, 0, 0),), 35, 35),
    "sofa_l": PropKind((("box", 150, 50, 0, -30), ("box", 50, 70, 50, 30)), 45, 40),       # canapé d'angle
    "bed": PropKind((("box", 100, 170, 0, 0),), 50, 45),
    "wardrobe": PropKind((("box", 80, 46, 0, 0),), 60, 50),
    "fridge": PropKind((("box", 62, 62, 0, 0),), 55, 50),
    "piano": PropKind((("box", 140, 60, 0, -45),                                           # piano à queue :
                       ("poly", ((-70, -15), (70, -15), (45, 60), (-10, 80), (-55, 55)))),   # clavier + caisse
                      70, 50),
    "stove": PropKind((("box", 60, 60, 0, 0),), 45, 40),
    "counter": PropKind((("box", 120, 40, 0, 0),), 40, 40),
    "bathtub": PropKind((("box", 80, 150, 0, 0),), 50, 40),
    "hay_bale": PropKind((("box", 80, 45, 0, 0),), 20, 25),
    "pew": PropKind((("box", 170, 34, 0, 0),), 35, 35),                                    # banc d'église
    "dumpster": PropKind((("box", 120, 70, 0, 0),), 90, 50),
    "car": PropKind((("box", 190, 86, 0, 0),), 150, 50),
}
ROOM_PROPS = (["chair"] * 3 + ["barrel"] * 2
              + ["crate", "table", "round_table", "bookshelf", "sofa_l", "bed", "wardrobe", "fridge", "piano"])
ROOM_PROPS_AREA = 800 * 800        # ROOM_PROPS meuble une pièce de cette surface ; au prorata pour les autres

# Thèmes de mobilier (champ « theme » des zones d'une carte) : types tirés au hasard et densité
# (meubles pour 100 000 px², soit une pièce d'environ 316 x 316). « mixed » = ancien mobilier générique.
THEMES: dict[str, tuple[list[str], float]] = {
    "mixed": (ROOM_PROPS, len(ROOM_PROPS) / ROOM_PROPS_AREA * 1e5),
    "living": (["sofa_l", "round_table", "bookshelf", "chair", "chair", "piano", "table", "barrel"], 2.0),
    "dining": (["table", "chair", "chair", "chair", "chair", "bookshelf", "wardrobe"], 2.2),
    "bedroom": (["bed", "wardrobe", "chair", "bookshelf", "crate"], 2.0),
    "kitchen": (["fridge", "stove", "counter", "counter", "table", "chair", "chair", "barrel"], 2.6),
    "bathroom": (["bathtub", "crate", "wardrobe"], 2.0),
    "library": (["bookshelf", "bookshelf", "bookshelf", "round_table", "chair", "piano"], 2.2),
    "hall": (["chair", "bookshelf", "table", "round_table", "piano"], 0.9),
    "office": (["table", "chair", "chair", "bookshelf", "wardrobe"], 2.0),
    "shop": (["counter", "counter", "bookshelf", "bookshelf", "bookshelf", "crate", "fridge"], 2.2),
    "storage": (["crate", "crate", "barrel", "barrel", "bookshelf", "wardrobe"], 2.6),
    "garage": (["car", "crate", "barrel", "barrel", "counter"], 1.2),
    "barn": (["hay_bale", "hay_bale", "hay_bale", "hay_bale", "crate", "crate", "barrel"], 1.6),
    "chapel": (["pew", "pew", "pew", "pew", "table"], 1.8),
    "farmyard": (["hay_bale", "hay_bale", "barrel", "crate"], 0.25),
    "garden": (["round_table", "chair", "barrel"], 0.12),
    "street": (["dumpster", "barrel", "crate"], 0.06),
}
DOOR_CLEARANCE = 110.0             # aucun meuble posé à moins de ça d'une porte au début d'une manche


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# --------------------------------------------------------------- navigation
class NavGrid:
    """Grille de navigation des bots, générée automatiquement à partir des murs de la carte (rien à régler à la
    main pour une nouvelle carte). Les meubles n'y figurent pas : les zombies les cassent. Les calculs de
    chemin sont délégués à tcod (bibliothèque C de référence pour la navigation sur grille en 2D)."""

    CARDINAL, DIAGONAL = 2, 3          # coûts d'un pas droit / en diagonale (≈ 1 : 1,41)

    def __init__(self, walls: list[Wall], w: float, h: float, obstacles: list[Obstacle] = (),
                 cell: float = NAV_CELL, margin: float = NAV_MARGIN) -> None:
        self.cell = cell
        self.cols, self.rows = int(w // cell), int(h // cell)
        cx = (np.arange(self.cols) + 0.5) * cell
        cy = (np.arange(self.rows) + 0.5) * cell
        gx, gy = np.meshgrid(cx, cy, indexing="ij")            # tableaux [colonne, ligne]
        blocked = np.zeros((self.cols, self.rows), dtype=bool)
        for wl in walls:                                        # murs à n'importe quel angle
            dx, dy = wl.x2 - wl.x1, wl.y2 - wl.y1
            k = np.clip(((gx - wl.x1) * dx + (gy - wl.y1) * dy) / max(dx * dx + dy * dy, 1e-9), 0, 1)
            dist = np.hypot(gx - (wl.x1 + k * dx), gy - (wl.y1 + k * dy))
            blocked |= dist < wl.t / 2 + margin
        for ob in obstacles:
            blocked |= np.hypot(gx - ob.x, gy - ob.y) < ob.r + margin
        self.blocked = blocked
        self.cost = np.where(blocked, 0, 1).astype(np.int32)    # 0 = infranchissable pour tcod

    def is_blocked(self, c: tuple[int, int]) -> bool:
        return bool(self.blocked[c])

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        return (int(clamp(x // self.cell, 0, self.cols - 1)), int(clamp(y // self.cell, 0, self.rows - 1)))

    def center(self, c: tuple[int, int]) -> tuple[float, float]:
        return ((c[0] + 0.5) * self.cell, (c[1] + 0.5) * self.cell)

    def nearest_free(self, c: tuple[int, int], radius: int = 3) -> tuple[int, int]:
        """Case libre la plus proche (un joueur collé à un angle de murs est dans une case « bloquée »)."""
        if not self.blocked[c]:
            return c
        i0, i1 = max(0, c[0] - radius), min(self.cols, c[0] + radius + 1)
        j0, j1 = max(0, c[1] - radius), min(self.rows, c[1] + radius + 1)
        free = np.argwhere(~self.blocked[i0:i1, j0:j1])
        if not len(free):
            return c
        d = (free[:, 0] + i0 - c[0]) ** 2 + (free[:, 1] + j0 - c[1]) ** 2
        i, j = free[int(np.argmin(d))]
        return (int(i + i0), int(j + j0))

    def distance_field(self, sources: list[tuple[float, float]]) -> np.ndarray:
        """Distance (par les couloirs) de chaque case à la source la plus proche ; « infini » si inatteignable."""
        dist = tcod.path.maxarray((self.cols, self.rows), dtype=np.int32)
        for x, y in sources:
            dist[self.nearest_free(self.cell_of(x, y))] = 0
        tcod.path.dijkstra2d(dist, self.cost, self.CARDINAL, self.DIAGONAL, out=dist)
        return dist

    def reachable(self, c: tuple[int, int], dist: np.ndarray) -> bool:
        return bool(dist[c] < UNREACHABLE)

    def descend(self, c: tuple[int, int], dist: np.ndarray, n: int) -> list[tuple[int, int]]:
        """Les n prochaines cases en descendant la carte des distances (vers la source la plus proche)."""
        if not self.reachable(c, dist):
            return []
        steps = tcod.path.hillclimb2d(dist, c, True, True)[1:n + 1]
        return [(int(i), int(j)) for i, j in steps]

    def path(self, start: tuple[float, float], goal: tuple[float, float]) -> list[tuple[float, float]]:
        """Chemin complet (points du monde) de start à goal, [] si impossible."""
        dist = self.distance_field([goal])
        cells = self.descend(self.nearest_free(self.cell_of(*start)), dist, self.cols * self.rows)
        if not cells and self.nearest_free(self.cell_of(*start)) != self.nearest_free(self.cell_of(*goal)):
            return []
        pts = [self.center(c) for c in cells]
        return [*pts[:-1], goal] if pts else [goal]


# ------------------------------------------------------------------ entités
@dataclass
class Settings:
    round_seconds: float = 150.0
    freeze_seconds: float = 10.0
    intermission_seconds: float = 8.0
    end_seconds: float = 8.0
    min_players: int = 2
    max_players: int = 24
    fill_to: int = 0          # complète avec des bots jusqu'à N joueurs (0 = aucun)
    map: str = "manoir"       # voir maps.MAPS


@dataclass(eq=False)
class Prop:
    id: int
    kind: str
    body: pymunk.Body
    shapes: list[pymunk.Shape]
    home: tuple[float, float, float]
    sent: tuple[float, float, float]
    max_hp: int = 1
    hp: int = 1
    broken: bool = False

    @property
    def hp_pct(self) -> int:
        return round(100 * self.hp / self.max_hp)


@dataclass(eq=False)
class BotBrain:
    path: list = field(default_factory=list)
    repath_t: float = 0.0
    check_t: float = 0.0
    last_pos: tuple[float, float] = (0.0, 0.0)
    wander: tuple[float, float] | None = None
    wander_t: float = 0.0
    careful_until: float = 0.0       # coincé contre un mur : on suit la pente case par case un moment
    wp: tuple[float, float] | None = None   # cap courant (None = foncer droit sur l'humain visé)
    replan_at: float = 0.0


@dataclass(eq=False)
class Player:
    id: int
    name: str
    body: pymunk.Body
    shape: pymunk.Circle
    role: int = HUMAN
    dx: float = 0.0
    dy: float = 0.0
    aim: float = 0.0
    kbx: float = 0.0
    kby: float = 0.0
    hit_cd: float = 0.0
    shot_cd: float = 0.0
    reload_t: float = 0.0
    ammo: int = MAG_SIZE
    slow_until: float = 0.0
    frozen_until: float = 0.0
    hp: int = ZOMBIE_HP                # n'a de sens que pour un zombie
    respawn_until: float = 0.0
    bot: BotBrain | None = None
    ctrl: pymunk.Body | None = None
    pivot: pymunk.PivotJoint | None = None

    @property
    def x(self) -> float:
        return self.body.position.x

    @property
    def y(self) -> float:
        return self.body.position.y


# -------------------------------------------------------------------- monde
class World:
    def __init__(self, settings: Settings | None = None, seed: int | None = 7) -> None:
        self.cfg = settings or Settings()
        self.rng = random.Random(seed)
        self.space = pymunk.Space()
        self.space.damping = GROUND_DAMPING
        self.players: dict[int, Player] = {}
        self.props: dict[int, Prop] = {}
        self._owner: dict[pymunk.Shape, tuple[str, int]] = {}
        self._ids = itertools.count(1)
        self.tick = 0
        self.now = 0.0
        self.phase = "wait"
        self.timer = 0.0
        self.winner: str | None = None
        self.freeze_until = 0.0
        self.events: list[dict] = []
        self.roster_dirty = True
        self._dirty_props: list[list] = []
        self._dirty_hp: dict[int, int] = {}       # id meuble -> PV en % (0 = cassé), à envoyer
        self._bot_n = 0
        self._flow: np.ndarray | None = None
        self._flow_at = -1e9
        self.map: MapDef = get_map(self.cfg.map)
        self.walls, self.doors = self.map.walls, self.map.doors
        self._build_static()
        self._build_props(random.Random(seed))
        self.nav = NavGrid(self.walls, self.map.w, self.map.h, self.map.obstacles)

    # ------------------------------------------------------------ construction
    def _build_static(self) -> None:
        """Murs = segments épais à bouts ronds (n'importe quel angle) ; obstacles = cercles. Fixes, indestructibles."""
        for wl in self.walls:
            shape = pymunk.Segment(self.space.static_body, (wl.x1, wl.y1), (wl.x2, wl.y2), wl.t / 2)
            shape.friction = 0.8
            shape.filter = ShapeFilter(categories=CAT_WALL)
            self.space.add(shape)
        for ob in self.map.obstacles:
            shape = pymunk.Circle(self.space.static_body, ob.r, (ob.x, ob.y))
            shape.friction = 0.8
            shape.filter = ShapeFilter(categories=CAT_WALL)
            self.space.add(shape)

    def _build_props(self, rng: random.Random) -> None:
        """Meubles posés par la carte, puis mobilier tiré au hasard selon le thème de chaque zone."""
        for fp in self.map.props:
            self._add_prop(fp.kind, fp.x, fp.y, fp.angle)
        for area in self.map.areas:
            if area.theme is None:
                continue
            pool, density = THEMES[area.theme]
            n = round(density * area.surface / 1e5)
            if area.spawn == "zombie" and self.map.name != "manoir":
                n //= 3                    # la salle des zombies n'a pas besoin d'être meublée
            if area.theme == "mixed":
                kinds = pool if n >= len(pool) else rng.sample(pool, n)
            else:
                kinds = rng.choices(pool, k=n)
            for kind in kinds:
                rad = PROP_KINDS[kind].radius
                for _ in range(60):
                    pt = area.random_point(rng, margin=rad * 0.5 + 10, tries=8)   # les murs : _free
                    if pt is None:
                        continue
                    x, y = pt
                    if any(math.hypot(x - dx, y - dy) < DOOR_CLEARANCE for dx, dy in self.doors):
                        continue
                    if not self._free(x, y, rad + 4):      # murs, obstacles et meubles déjà posés
                        continue
                    break
                else:
                    continue
                angle = 0.0 if rng.random() < 0.5 else math.pi / 2
                if rng.random() < 0.25:
                    angle = rng.uniform(0, math.pi)
                self._add_prop(kind, x, y, angle)

    def _add_prop(self, kind: str, x: float, y: float, angle: float) -> Prop:
        k = PROP_KINDS[kind]
        body = pymunk.Body()               # masse et inertie calculées par pymunk à partir des formes
        body.position = (x, y)
        body.angle = angle
        shapes: list[pymunk.Shape] = []
        for part in k.parts:
            if part[0] == "box":
                _, w, h, dx, dy = part
                shape = pymunk.Poly(body, [(dx - w / 2, dy - h / 2), (dx + w / 2, dy - h / 2),
                                           (dx + w / 2, dy + h / 2), (dx - w / 2, dy + h / 2)])
            elif part[0] == "circle":
                _, r, dx, dy = part
                shape = pymunk.Circle(body, r, (dx, dy))
            else:
                shape = pymunk.Poly(body, list(part[1]))
            shape.friction = 0.6
            shape.elasticity = 0.1
            shape.filter = ShapeFilter(categories=CAT_PROP)
            shapes.append(shape)
        density = k.mass * MASS_SCALE / sum(sh.area for sh in shapes)
        for sh in shapes:
            sh.density = density
        self.space.add(body, *shapes)
        pid = next(self._ids)
        prop = Prop(pid, kind, body, shapes, (x, y, angle), (x, y, angle), k.hp, k.hp)
        self.props[pid] = prop
        for sh in shapes:
            self._owner[sh] = ("prop", pid)
        return prop

    def _reset_props(self) -> None:
        for pr in self.props.values():
            if pr.broken:
                self.space.add(pr.body, *pr.shapes)
                for sh in pr.shapes:
                    self._owner[sh] = ("prop", pr.id)
                pr.broken = False
            if pr.hp != pr.max_hp:
                pr.hp = pr.max_hp
                self._dirty_hp[pr.id] = 100
            x, y, a = pr.home
            pr.body.position = (x, y)
            pr.body.angle = a
            pr.body.velocity = (0, 0)
            pr.body.angular_velocity = 0
            self.space.reindex_shapes_for_body(pr.body)
            pr.sent = (-1e9, -1e9, -1e9)   # force le renvoi de la position

    # ----------------------------------------------------------------- joueurs
    @property
    def real_count(self) -> int:
        return sum(1 for p in self.players.values() if p.bot is None)

    def humans(self) -> list[Player]:
        return [p for p in self.players.values() if p.role == HUMAN]

    def zombies(self) -> list[Player]:
        return [p for p in self.players.values() if p.role == ZOMBIE]

    def can_join(self) -> bool:
        return self.real_count < self.cfg.max_players

    def add_player(self, name: str, bot: bool = False) -> Player:
        if not self.players and not bot:
            self._enter_wait()
            self.events, self._dirty_hp = [], {}   # rien de périmé (serveur resté vide) pour le premier arrivant
        pid = next(self._ids)
        clean = "".join(ch for ch in name if ch.isprintable()).strip()[:16]
        if bot:
            self._bot_n += 1
            clean = f"Bot {self._bot_n}"
        body = pymunk.Body(PLAYER_MASS, float("inf"))
        shape = pymunk.Circle(body, PLAYER_R)
        shape.friction = 0.2
        shape.filter = ShapeFilter(categories=CAT_HUMAN)
        ctrl = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        pivot = pymunk.PivotJoint(ctrl, body, (0, 0), (0, 0))
        pivot.max_bias = 0                 # pas de correction de position : simple moteur de vitesse
        pivot.max_force = DRIVE_FORCE
        p = Player(id=pid, name=clean or f"Joueur{pid}", body=body, shape=shape,
                   bot=BotBrain() if bot else None, ctrl=ctrl, pivot=pivot)
        if self.phase == "play":
            self._set_role(p, ZOMBIE)
            body.position = self._spawn_point(self.map.zombie_areas)
        else:
            body.position = self._spawn_point(self._human_rooms())
        ctrl.position = body.position
        self.space.add(body, shape, ctrl, pivot)
        self._owner[shape] = ("player", pid)
        self.players[pid] = p
        self.roster_dirty = True
        if not bot:
            self.sync_bots()
        return p

    def remove_player(self, pid: int) -> None:
        p = self.players.pop(pid, None)
        if p is None:
            return
        self.space.remove(p.body, p.shape, p.ctrl, p.pivot)
        self._owner.pop(p.shape, None)
        self.roster_dirty = True
        # Plus de zombie : un humain le devient — sauf si plus aucun vrai joueur (les bots vont tous partir).
        if self.phase == "play" and not self.zombies() and self.humans() and self.real_count:
            self._promote_zero(self.rng.choice(self.humans()))
        if p.bot is None:
            self.sync_bots()

    def sync_bots(self) -> None:
        """Complète avec des bots jusqu'à fill_to joueurs ; aucun bot sans humain réel."""
        real = self.real_count
        bots = [p for p in self.players.values() if p.bot is not None]
        want = max(0, self.cfg.fill_to - real) if real > 0 else 0
        while len(bots) < want and len(self.players) < self.cfg.max_players:
            bots.append(self.add_player("", bot=True))
        while len(bots) > want:
            self.remove_player(bots.pop().id)

    def set_input(self, pid: int, dx: float, dy: float, aim: float) -> None:
        p = self.players.get(pid)
        if p is None or p.bot is not None or not all(map(math.isfinite, (dx, dy, aim))):
            return
        m = math.hypot(dx, dy)
        if m > 1:
            dx, dy = dx / m, dy / m
        p.dx, p.dy, p.aim = dx, dy, aim

    def act(self, pid: int, kind: str) -> None:
        p = self.players.get(pid)
        if p is None:
            return
        if kind == "hit" or (kind == "shoot" and p.role == ZOMBIE):
            self.hit(p)
        elif kind == "shoot":
            self.shoot(p)

    def _set_role(self, p: Player, role: int) -> None:
        p.role = role
        p.hp = ZOMBIE_HP
        p.shape.filter = ShapeFilter(categories=CAT_ZOMBIE if role == ZOMBIE else CAT_HUMAN)

    # ------------------------------------------------------------------ spawns
    def _free(self, x: float, y: float, r: float) -> bool:
        return self.space.point_query_nearest((x, y), r, ShapeFilter(mask=ALL_SOLID)) is None

    def _spawn_point(self, rooms: list[int], taken: list[tuple[float, float]] | None = None) -> tuple[float, float]:
        taken = taken or []
        x = y = 0.0
        for _ in range(80):
            pt = self.map.areas[self.rng.choice(rooms)].random_point(self.rng, margin=PLAYER_R + 20, tries=10)
            if pt is None:
                continue
            x, y = pt
            if self._free(x, y, PLAYER_R + 8) and all(math.hypot(x - tx, y - ty) > 60 for tx, ty in taken):
                break
        return x, y

    def _human_rooms(self) -> list[int]:
        return self.map.human_areas

    def _respawn_all_as_humans(self) -> None:
        taken: list[tuple[float, float]] = []
        rooms = self._human_rooms()
        for p in self.players.values():
            self._set_role(p, HUMAN)
            pos = self._spawn_point(rooms, taken)
            taken.append(pos)
            self._teleport(p, pos)
            p.ammo, p.reload_t, p.shot_cd, p.hit_cd = MAG_SIZE, 0.0, 0.0, 0.0
            p.slow_until = p.frozen_until = p.respawn_until = 0.0
            p.kbx = p.kby = 0.0

    def _teleport(self, p: Player, pos: tuple[float, float]) -> None:
        p.body.position = pos
        p.body.velocity = (0, 0)
        p.ctrl.position = pos
        p.ctrl.velocity = (0, 0)
        self.space.reindex_shapes_for_body(p.body)

    # ------------------------------------------------------------ phases/manche
    def _enter_wait(self) -> None:
        self.phase, self.timer, self.winner = "wait", 0.0, None
        self._reset_props()
        self._respawn_all_as_humans()

    def _enter_intermission(self, reset: bool = True) -> None:
        self.phase, self.timer, self.winner = "intermission", self.cfg.intermission_seconds, None
        if reset:
            self._reset_props()
            self._respawn_all_as_humans()

    def _start_round(self) -> None:
        self._reset_props()
        self._respawn_all_as_humans()
        self.phase, self.timer, self.winner = "play", self.cfg.round_seconds, None
        self._promote_zero(self.rng.choice(list(self.players.values())), first=True)

    def _promote_zero(self, p: Player, first: bool = False) -> None:
        self._set_role(p, ZOMBIE)
        self._teleport(p, self._spawn_point(self.map.zombie_areas))
        if first:
            p.frozen_until = self.freeze_until = self.now + self.cfg.freeze_seconds
        self.events.append({"k": "zero", "id": p.id})

    def _end_round(self, winner: str | None) -> None:
        self.phase, self.timer, self.winner = "end", self.cfg.end_seconds, winner or "none"
        self.events.append({"k": "end", "w": self.winner})

    def _phase_logic(self, dt: float) -> None:
        n = len(self.players)
        if self.phase == "wait":
            if n >= self.cfg.min_players:
                self._enter_intermission(reset=False)
        elif self.phase == "intermission":
            if n < self.cfg.min_players:
                self.phase = "wait"
                return
            self.timer -= dt
            if self.timer <= 0:
                self._start_round()
        elif self.phase == "play":
            self.timer -= dt
            if n < self.cfg.min_players:
                self._end_round(None)
            elif self.timer <= 0:
                self._end_round("humans")
        elif self.phase == "end":
            self.timer -= dt
            if self.timer <= 0:
                if n >= self.cfg.min_players:
                    self._enter_intermission()
                else:
                    self._enter_wait()

    # -------------------------------------------------------------- simulation
    def step(self, dt: float = 1.0 / TICK_RATE) -> None:
        self.tick += 1
        self.now += dt
        self._phase_logic(dt)
        for p in self.players.values():
            p.hit_cd = max(0.0, p.hit_cd - dt)
            p.shot_cd = max(0.0, p.shot_cd - dt)
            if p.reload_t > 0:
                p.reload_t -= dt
                if p.reload_t <= 0:
                    p.ammo, p.reload_t = MAG_SIZE, 0.0
            if p.bot is not None:
                self._bot_think(p, dt)
        self._physics(dt)
        if self.phase == "play":
            self._infection()
        self._collect_dirty_props()

    def _physics(self, dt: float) -> None:
        h = dt / SUBSTEPS
        for _ in range(SUBSTEPS):
            for p in self.players.values():
                self._drive(p)
            self.space.step(h)
        decay = math.exp(-KNOCKBACK_DECAY * dt)
        for p in self.players.values():
            p.ctrl.position = p.body.position
            p.kbx *= decay
            p.kby *= decay

    def _drive(self, p: Player) -> None:
        if self.now < p.frozen_until:
            vx = vy = 0.0
        else:
            speed = ZOMBIE_SPEED if p.role == ZOMBIE else HUMAN_SPEED
            if self.now < p.slow_until:
                speed *= SLOW_FACTOR
            vx, vy = p.dx * speed, p.dy * speed
        p.ctrl.velocity = (vx + p.kbx, vy + p.kby)

    def _infection(self) -> None:
        zombies = [z for z in self.zombies() if self.now >= z.frozen_until]
        for h in self.humans():
            for z in zombies:
                if math.hypot(z.x - h.x, z.y - h.y) <= INFECT_DIST:
                    self._infect(h, z)
                    break
        if not self.humans():
            self._end_round("zombies")

    def _infect(self, h: Player, z: Player) -> None:
        self._set_role(h, ZOMBIE)
        h.frozen_until = self.now + INFECT_STUN
        h.slow_until = 0.0
        self.events.append({"k": "infect", "id": h.id, "by": z.id, "x": round(h.x, 1), "y": round(h.y, 1)})

    # ----------------------------------------------------------------- actions
    def hit(self, p: Player) -> bool:
        if p.hit_cd > 0 or self.now < p.frozen_until:
            return False
        p.hit_cd = HIT_COOLDOWN
        ax, ay = math.cos(p.aim), math.sin(p.aim)
        seen: set[tuple[str, int]] = set()    # par entité : un meuble à plusieurs formes n'est frappé qu'une fois
        touched = 0
        for d in (HIT_REACH * 0.5, HIT_REACH):
            for info in self.space.point_query((p.x + ax * d, p.y + ay * d), HIT_RADIUS, HIT_FILTER):
                owner = self._owner.get(info.shape)
                if info.shape is p.shape or owner is None or owner in seen:
                    continue
                seen.add(owner)
                kind, eid = owner
                touched += 1
                if kind == "prop":
                    pr = self.props[eid]
                    pr.body.apply_impulse_at_world_point((ax * HIT_IMPULSE * MASS_SCALE, ay * HIT_IMPULSE * MASS_SCALE), info.point)
                    if p.role == ZOMBIE:       # seuls les zombies abîment les barricades
                        self._damage_prop(pr)
                elif eid in self.players:
                    other = self.players[eid]
                    other.kbx += ax * KNOCKBACK
                    other.kby += ay * KNOCKBACK
                    if p.role == HUMAN and other.role == ZOMBIE:
                        self._damage_zombie(other, MELEE_DAMAGE, p)
        self.events.append({"k": "hit", "id": p.id, "x": round(p.x + ax * 28, 1),
                            "y": round(p.y + ay * 28, 1), "a": round(p.aim, 2), "n": touched})
        return True

    def _damage_zombie(self, z: Player, dmg: int, by: Player) -> None:
        if self.now < z.frozen_until:          # figé (réveil, infection, réapparition) = invulnérable
            return
        z.hp -= dmg
        if z.hp > 0:
            return
        self.events.append({"k": "kill", "id": z.id, "by": by.id, "x": round(z.x, 1), "y": round(z.y, 1)})
        z.hp = ZOMBIE_HP
        z.respawn_until = z.frozen_until = self.now + RESPAWN_TIME
        z.slow_until = 0.0
        z.kbx = z.kby = 0.0
        self._teleport(z, self._spawn_point(self.map.zombie_areas))

    def _damage_prop(self, pr: Prop) -> None:
        pr.hp -= 1
        self._dirty_hp[pr.id] = pr.hp_pct
        if pr.hp > 0:
            return
        pr.broken = True
        self.space.remove(pr.body, *pr.shapes)
        for sh in pr.shapes:
            self._owner.pop(sh, None)
        self.events.append({"k": "break", "id": pr.id, "x": round(pr.body.position.x, 1),
                            "y": round(pr.body.position.y, 1)})

    def shoot(self, p: Player) -> bool:
        if p.role != HUMAN or p.shot_cd > 0 or p.reload_t > 0 or self.now < p.frozen_until:
            return False
        if p.ammo <= 0:
            p.reload_t = RELOAD_TIME
            return False
        p.ammo -= 1
        p.shot_cd = SHOT_COOLDOWN
        if p.ammo == 0:
            p.reload_t = RELOAD_TIME
        ax, ay = math.cos(p.aim), math.sin(p.aim)
        start = (p.x + ax * (PLAYER_R + 2), p.y + ay * (PLAYER_R + 2))
        end = (p.x + ax * SHOT_RANGE, p.y + ay * SHOT_RANGE)
        info = self.space.segment_query_first(start, end, 0, SHOT_FILTER)
        hit_kind = ""
        if info is not None:
            end = (info.point.x, info.point.y)
            owner = self._owner.get(info.shape)
            if owner and owner[0] == "prop":
                self.props[owner[1]].body.apply_impulse_at_world_point((ax * SHOT_IMPULSE * MASS_SCALE, ay * SHOT_IMPULSE * MASS_SCALE), info.point)
                hit_kind = "prop"
            elif owner and owner[0] == "player" and owner[1] in self.players:
                z = self.players[owner[1]]
                z.slow_until = self.now + SLOW_TIME
                z.kbx += ax * SHOT_KNOCKBACK
                z.kby += ay * SHOT_KNOCKBACK
                self._damage_zombie(z, BULLET_DAMAGE, p)
                hit_kind = "zombie"
            else:
                hit_kind = "wall"
        self.events.append({"k": "shot", "id": p.id, "x1": round(start[0], 1), "y1": round(start[1], 1),
                            "x2": round(end[0], 1), "y2": round(end[1], 1), "h": hit_kind})
        return True

    # -------------------------------------------------------------------- bots
    def _los(self, a: tuple[float, float], b: tuple[float, float], radius: float = PLAYER_R * 0.7) -> bool:
        """Aucun mur entre a et b pour un objet de ce rayon (balle : fin ; corps entier : PLAYER_R)."""
        return self.space.segment_query_first(a, b, radius, WALL_ONLY) is None

    def _body_clear(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        """Un joueur peut-il glisser en ligne droite de a à b sans accrocher un mur ? On échantillonne le trajet :
        la requête « segment épais » de pymunk rate les murs dont le point de départ est déjà au contact."""
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) // 15))
        for i in range(1, n + 1):
            k = i / n
            pt = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
            if self.space.point_query_nearest(pt, PLAYER_R + 2, WALL_ONLY) is not None:
                return False
        return True

    def _humans_flow(self) -> np.ndarray:
        """Carte des distances vers l'humain le plus proche, partagée par tous les zombies, rafraîchie 4 fois/s."""
        if self.now - self._flow_at >= FLOW_REFRESH:
            self._flow = self.nav.distance_field([(h.x, h.y) for h in self.humans()])
            self._flow_at = self.now
        return self._flow

    def _zombie_waypoint(self, p: Player) -> tuple[float, float] | None:
        """Prochain point à viser : on descend la pente vers l'humain le plus proche (par les couloirs),
        et on vise la case la plus lointaine encore atteignable en ligne droite pour tout le corps."""
        field = self._humans_flow()
        nav = self.nav
        here = nav.nearest_free(nav.cell_of(p.x, p.y))
        lookahead = 1 if self.now < p.bot.careful_until else FLOW_LOOKAHEAD
        best = None
        for c in nav.descend(here, field, lookahead):
            pt = nav.center(c)
            if best is None or self._body_clear((p.x, p.y), pt):
                best = pt
            else:
                break
        return best

    def _bot_think(self, p: Player, dt: float) -> None:
        b = p.bot
        if self.now < p.frozen_until:
            p.dx = p.dy = 0.0
            return
        pos = (p.x, p.y)
        if p.role == ZOMBIE:
            targets = self.humans()
            if not targets:
                p.dx = p.dy = 0.0
                return
            t = min(targets, key=lambda h: (h.x - p.x) ** 2 + (h.y - p.y) ** 2)
            goal = (t.x, t.y)
            if self.now >= b.replan_at:
                b.replan_at = self.now + self.rng.uniform(*BOT_REPLAN)
                if math.hypot(t.x - p.x, t.y - p.y) < 300 and self._body_clear(pos, goal):
                    b.wp = None                # en vue et tout proche : on fonce droit dessus
                else:
                    b.wp = self._zombie_waypoint(p) or goal
            wp = goal if b.wp is None else b.wp
            vx, vy = wp[0] - p.x, wp[1] - p.y
            n = math.hypot(vx, vy) or 1.0
            p.dx, p.dy = vx / n, vy / n
            p.aim = math.atan2(vy, vx)
            b.check_t += dt          # coincé (meuble, barricade) ? on frappe
            if b.check_t >= 0.4:
                stuck = math.hypot(p.x - b.last_pos[0], p.y - b.last_pos[1]) < 12
                if stuck and self.hit(p) and self.events[-1]["n"] == 0:
                    b.careful_until = self.now + 1.0     # rien à frapper : c'est un mur, on décroche
                b.last_pos, b.check_t = pos, 0.0
        else:
            zs = [z for z in self.zombies() if self.now >= z.respawn_until]
            near = min(zs, key=lambda z: (z.x - p.x) ** 2 + (z.y - p.y) ** 2) if zs else None
            d = math.hypot(near.x - p.x, near.y - p.y) if near else 1e9
            if near is not None and d < 380:
                vx, vy = p.x - near.x, p.y - near.y
                n = math.hypot(vx, vy) or 1.0
                p.dx, p.dy = 0.9 * vx / n, 0.9 * vy / n
                p.aim = math.atan2(near.y - p.y, near.x - p.x)
                if d < 450 and self._los(pos, (near.x, near.y)) and self.rng.random() < 0.3:
                    self.shoot(p)
            else:
                b.wander_t -= dt
                if b.wander is None or b.wander_t <= 0 or math.hypot(b.wander[0] - p.x, b.wander[1] - p.y) < 30:
                    b.wander = (clamp(p.x + self.rng.uniform(-300, 300), 40, self.map.w - 40),
                                clamp(p.y + self.rng.uniform(-300, 300), 40, self.map.h - 40))
                    b.wander_t = self.rng.uniform(2, 5)
                vx, vy = b.wander[0] - p.x, b.wander[1] - p.y
                n = math.hypot(vx, vy) or 1.0
                p.dx, p.dy = 0.5 * vx / n, 0.5 * vy / n
                p.aim = math.atan2(vy, vx)

    # --------------------------------------------------------------- snapshots
    def _collect_dirty_props(self) -> None:
        for pr in self.props.values():
            if pr.broken:
                continue
            x, y, a = pr.body.position.x, pr.body.position.y, pr.body.angle
            sx, sy, sa = pr.sent
            if abs(x - sx) > 0.2 or abs(y - sy) > 0.2 or abs(a - sa) > 0.004:
                pr.sent = (x, y, a)
                self._dirty_props.append([pr.id, round(x, 1), round(y, 1), round(a, 3)])

    def props_full(self) -> list[list]:
        return [[pr.id, round(pr.body.position.x, 1), round(pr.body.position.y, 1), round(pr.body.angle, 3)]
                for pr in self.props.values()]

    def props_hp(self) -> list[list[int]]:
        return [[pr.id, pr.hp_pct] for pr in self.props.values()]

    def names(self) -> dict[int, str]:
        return {p.id: p.name for p in self.players.values()}

    def static_info(self) -> dict:
        return {
            "v": PROTOCOL_VERSION, "map": self.map.name, "w": self.map.w, "h": self.map.h,
            "base": self.map.base,
            "areas": [[a.ground, [[round(x, 1), round(y, 1)] for x, y in a.poly]] for a in self.map.areas],
            "walls": [[round(wl.x1, 1), round(wl.y1, 1), round(wl.x2, 1), round(wl.y2, 1), wl.t, wl.style]
                      for wl in self.walls],
            "obstacles": [[ob.kind, ob.x, ob.y, ob.r] for ob in self.map.obstacles],
            "kinds": {name: [list(part) if part[0] != "poly" else ["poly", [list(pt) for pt in part[1]]]
                             for part in k.parts] for name, k in PROP_KINDS.items()},
            "props": [[pr.id, pr.kind] for pr in self.props.values()],
            "pos": self.props_full(),
            "ps": self.props_hp(),
            "names": self.names(),
            "cfg": {"round": self.cfg.round_seconds, "freeze": self.cfg.freeze_seconds,
                    "min": self.cfg.min_players, "player_r": PLAYER_R},
        }

    def me(self, pid: int) -> list:
        p = self.players.get(pid)
        if p is None:
            return [0, 0]
        return [p.ammo, 1 if p.reload_t > 0 else 0]

    def snapshot(self) -> dict:
        """État global (identique pour tous les clients) ; consomme événements et props modifiés."""
        players = []
        for p in self.players.values():
            flags = ((1 if self.now < p.slow_until else 0) | (2 if self.now < p.frozen_until else 0)
                     | (4 if self.now < p.respawn_until else 0))
            hp = round(100 * p.hp / ZOMBIE_HP) if p.role == ZOMBIE else 100
            players.append([p.id, round(p.x, 1), round(p.y, 1), round(p.aim, 2), p.role, flags, hp])
        fz = self.freeze_until - self.now if self.phase == "play" else 0.0
        snap = {
            "t": "s", "k": self.tick, "ph": self.phase, "tl": round(max(0.0, self.timer), 1),
            "w": self.winner, "fz": round(max(0.0, fz), 1),
            "n": [len(self.humans()), len(self.zombies())],
            "p": players, "pr": self._dirty_props, "ev": self.events,
        }
        if self._dirty_hp:
            snap["ps"] = [[pid, pct] for pid, pct in self._dirty_hp.items()]
            self._dirty_hp = {}
        if self.tick % 90 == 0:
            snap["pf"] = self.props_full()
            snap["ps"] = self.props_hp()
        if self.roster_dirty:
            snap["names"] = self.names()
            self.roster_dirty = False
        self._dirty_props, self.events = [], []
        return snap
