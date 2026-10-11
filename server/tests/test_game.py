import math

import pymunk
import pytest

from app.game import (
    BULLET_DAMAGE,
    CAT_ZOMBIE,
    FLOW_REFRESH,
    HIT_COOLDOWN,
    HUMAN,
    INFECT_DIST,
    MAG_SIZE,
    MELEE_DAMAGE,
    PLAYER_R,
    PROP_HP,
    RESPAWN_TIME,
    ZOMBIE,
    ZOMBIE_HP,
    Settings,
    World,
)
from app.maps import MAPS

DT = 1 / 30


def empty_world(**kw) -> World:
    """Monde sans meubles : pour isoler une règle."""
    w = World(Settings(**kw), seed=7)
    for pr in list(w.props.values()):
        w.space.remove(pr.body, pr.shape)
    w.props.clear()
    return w


def run(w: World, seconds: float) -> None:
    for _ in range(int(seconds / DT)):
        w.step(DT)


def start_round(w: World, n: int = 2):
    ps = [w.add_player(f"P{i}") for i in range(n)]
    run(w, w.cfg.intermission_seconds + 1)
    assert w.phase == "play"
    return ps


# ------------------------------------------------------------------- carte
def test_map_has_walls_and_many_props_with_free_doors():
    w = World(seed=7)
    assert len(w.walls) >= 10 and len(w.props) >= 70
    for dx, dy in w.doors:
        assert w.space.point_query_nearest((dx, dy), 40, __import__("pymunk").ShapeFilter(mask=2)) is None, \
            "un meuble bloque une porte au départ"


def test_players_cannot_leave_the_map():
    w = empty_world()
    p = w.add_player("A")
    w._teleport(p, (30, 30))
    w.set_input(p.id, -1, -1, 0)
    run(w, 3)
    assert 0 <= p.x <= 2400 and 0 <= p.y <= 1600
    assert p.x >= PLAYER_R - 2 and p.y >= PLAYER_R - 2


def test_player_speed_without_obstacle():
    w = empty_world()
    p = w.add_player("A")
    w._teleport(p, (100, 400))
    w.set_input(p.id, 1, 0, 0)
    run(w, 1)
    assert 150 < p.x - 100 < 220


@pytest.mark.parametrize("name", list(MAPS))
def test_every_map_is_connected_and_furnished(name):
    """Depuis la salle des zombies, on atteint toutes les pièces ; aucune porte n'est bouchée au départ."""
    w = World(Settings(map=name), seed=7)
    assert len(w.props) >= 70
    zx0, zy0, zx1, zy1 = w.map.rooms[w.map.zombie_room]
    start = ((zx0 + zx1) / 2, (zy0 + zy1) / 2)
    for x0, y0, x1, y1 in w.map.rooms:
        assert w.nav.path(start, ((x0 + x1) / 2, (y0 + y1) / 2)), (x0, y0)
    for dx, dy in w.doors:
        assert w._free(dx, dy, PLAYER_R + 4), (dx, dy)


def test_unknown_map_is_refused():
    with pytest.raises(ValueError):
        World(Settings(map="atlantide"))


def test_zombie_bot_crosses_the_long_map():
    """Sur l'entrepôt, un bot zombie part de sa salle (à gauche) et rejoint un humain dans la salle finale."""
    w = World(Settings(map="entrepot", fill_to=0, intermission_seconds=999), seed=3)   # pas de manche : rôles figés
    for pr in list(w.props.values()):          # sans meubles : on teste la navigation, pas la casse
        w.space.remove(pr.body, pr.shape)
    w.props.clear()
    h = w.add_player("H")
    z = w.add_player("Z", bot=True)
    w._set_role(z, ZOMBIE)
    w._teleport(z, (300, 600))
    w._teleport(h, (3800, 600))
    for _ in range(int(40 / DT)):
        w.step(DT)
        if math.hypot(z.x - h.x, z.y - h.y) < 80:
            break
    assert math.hypot(z.x - h.x, z.y - h.y) < 80


# --------------------------------------------------------- physique / frappe
def test_hit_moves_light_prop_more_than_heavy_prop():
    moved = {}
    for kind in ("chair", "wardrobe"):
        w = empty_world()
        pr = w._add_prop(kind, 400, 400, 0)
        p = w.add_player("A")
        w._teleport(p, (330, 400))
        p.aim = 0
        assert w.hit(p)
        run(w, 3)
        moved[kind] = pr.body.position.x - 400
    assert moved["chair"] > 100 > moved["wardrobe"] > 5


def test_walking_into_heavy_furniture_barely_moves_it():
    w = empty_world()
    pr = w._add_prop("wardrobe", 400, 400, 0)
    p = w.add_player("A")
    w._teleport(p, (330, 400))
    w.set_input(p.id, 1, 0, 0)
    run(w, 3)
    assert pr.body.position.x - 400 < 15


def test_barricade_blocks_a_door():
    """Un meuble lourd posé dans une porte arrête un joueur."""
    w = empty_world()
    dx, dy = w.doors[0]
    w._add_prop("bed", dx, dy, 0)             # lit 100 x 170 : couvre la porte de 120
    p = w.add_player("A")
    w._teleport(p, (dx - 120, dy))
    w.set_input(p.id, 1, 0, 0)
    run(w, 3)
    assert p.x < dx - 20


def test_hit_event_counts_what_was_touched():
    """Le client choisit le son (dans le vide / impact) d'après le champ « n »."""
    w = empty_world()
    p = w.add_player("A")
    w._teleport(p, (330, 400))
    p.aim = 0
    assert w.hit(p)
    assert w.events[-1]["k"] == "hit" and w.events[-1]["n"] == 0
    w._add_prop("chair", 400, 400, 0)
    run(w, 0.6)
    w.events.clear()
    assert w.hit(p)
    assert w.events[-1]["n"] == 1


def hit_n(w, p, n):
    """Frappe n fois en respectant le temps de recharge."""
    for _ in range(n):
        run(w, HIT_COOLDOWN + DT)
        assert w.hit(p)


def test_prop_breaks_after_enough_hits_and_frees_the_way():
    w = empty_world()
    pr = w._add_prop("chair", 400, 400, 0)
    p = w.add_player("A")
    w._teleport(p, (360, 400))
    p.aim = 0
    for i in range(PROP_HP["chair"]):
        assert not pr.broken and pr.hp == PROP_HP["chair"] - i
        pr.body.position, pr.body.velocity = (400, 400), (0, 0)   # une chaise vole loin : on la remet devant
        w.space.reindex_shapes_for_body(pr.body)
        hit_n(w, p, 1)
    assert pr.broken and pr.shape not in w.space.shapes
    assert any(e["k"] == "break" and e["id"] == pr.id for e in w.snapshot()["ev"])


def test_heavy_props_need_more_hits():
    assert PROP_HP["wardrobe"] > PROP_HP["table"] > PROP_HP["chair"]


def test_broken_props_come_back_next_round_and_client_is_told():
    w = World(Settings(intermission_seconds=0.5, end_seconds=0.5, round_seconds=1), seed=7)
    start_round(w)
    pr = next(iter(w.props.values()))
    for _ in range(pr.max_hp):
        w._damage_prop(pr)
    assert pr.broken
    snap = w.snapshot()
    assert [pr.id, 0] in snap["ps"]
    run(w, 3)                                     # fin de manche puis entracte : remise en place
    assert not pr.broken and pr.hp == pr.max_hp and pr.shape in w.space.shapes
    assert any(pid == pr.id and pct == 100 for pid, pct in w.snapshot()["ps"])


def test_zombie_bot_breaks_through_a_barricade():
    """Fin du « Mexican standoff » : une armoire bloque la porte, le bot zombie finit par la casser."""
    w = empty_world(intermission_seconds=999)     # pas de nouvelle manche (qui remettrait le lit)
    dx, dy = w.doors[0]                            # porte verticale du manoir en (800, 360)
    wall = w._add_prop("bed", dx, dy, 0)          # lit 100 x 170 : couvre toute la porte
    wall.body.body_type = pymunk.Body.KINEMATIC   # coincé : impossible de le pousser, il faut le casser
    h = w.add_player("H")
    z = w.add_player("Z", bot=True)
    w._set_role(z, ZOMBIE)
    w._teleport(z, (dx - 150, dy))
    w._teleport(h, (dx + 200, dy))
    h.frozen_until = 1e9                          # l'humain ne bouge pas
    run(w, 25)
    assert wall.broken
    assert math.hypot(z.x - h.x, z.y - h.y) < 120


def test_hit_cooldown():
    w = empty_world()
    p = w.add_player("A")
    assert w.hit(p) and not w.hit(p)
    run(w, 0.6)
    assert w.hit(p)


# -------------------------------------------------------------------- tir
def test_shot_pushes_prop_and_costs_ammo():
    w = empty_world()
    pr = w._add_prop("chair", 700, 400, 0)
    p = w.add_player("A")
    w._teleport(p, (400, 400))
    p.aim = 0
    assert w.shoot(p)
    assert p.ammo == MAG_SIZE - 1
    run(w, 2)
    assert pr.body.position.x > 710
    assert any(e["k"] == "shot" and e["h"] == "prop" for e in w.snapshot()["ev"])


def test_bullets_pass_through_friends():
    """Pas de tir ami : un humain placé dans la ligne de tir ne bloque ni ne subit le tir."""
    w = empty_world()
    a, friend, z = w.add_player("A"), w.add_player("F"), w.add_player("Z")
    w._set_role(z, ZOMBIE)
    w._teleport(a, (300, 400))
    w._teleport(friend, (450, 400))
    w._teleport(z, (700, 400))
    a.aim = 0
    w.shoot(a)
    assert z.slow_until > w.now
    assert friend.slow_until == 0 and friend.kbx == 0


def test_shot_hits_zombie_and_slows_it():
    w = empty_world()
    a, z = w.add_player("A"), w.add_player("Z")
    w._set_role(z, ZOMBIE)
    w._teleport(a, (300, 400))
    w._teleport(z, (600, 400))
    a.aim = 0
    w.shoot(a)
    assert z.slow_until > w.now
    z.dx = 1
    x0 = z.x
    run(w, 1)
    slowed = z.x - x0
    run(w, 2)                      # ralentissement fini
    x1 = z.x
    run(w, 1)
    assert slowed < 0.7 * (z.x - x1)


def zombie_target(w, x=500, y=400):
    """Humain qui vise un zombie placé droit devant lui."""
    h = w.add_player("H")
    z = w.add_player("Z")
    w._set_role(z, ZOMBIE)
    w._teleport(h, (x - 200, y))
    w._teleport(z, (x, y))
    h.aim = 0
    return h, z


def test_bullets_eventually_kill_a_zombie_who_respawns_in_his_room():
    w = empty_world()
    h, z = zombie_target(w)
    shots = 0
    while not any(e["k"] == "kill" for e in w.events):
        w._teleport(z, (500, 400))               # le recul l'éloigne : on le remet en place
        z.kbx = z.kby = 0.0
        if w.shoot(h):
            shots += 1
        run(w, 0.4)
        assert shots <= 20
    assert shots == math.ceil(ZOMBIE_HP / BULLET_DAMAGE)
    x0, y0, x1, y1 = w.map.rooms[w.map.zombie_room]
    assert x0 <= z.x <= x1 and y0 <= z.y <= y1 and z.hp == ZOMBIE_HP
    assert w.snapshot()["p"][1][5] & 4            # drapeau « en réapparition »


def test_melee_from_a_human_hurts_zombies_but_not_humans():
    w = empty_world()
    h, z = zombie_target(w, 500, 400)
    w._teleport(h, (450, 400))
    other = w.add_player("H2")
    for _ in range(2):
        run(w, HIT_COOLDOWN + DT)
        w._teleport(h, (450, 400))
        w._teleport(z, (500, 400))
        assert w.hit(h)
    assert z.hp == ZOMBIE_HP - 2 * MELEE_DAMAGE
    assert other.hp == ZOMBIE_HP                  # PV inutilisés pour un humain : rien ne bouge
    w._set_role(h, ZOMBIE)                         # un zombie ne blesse pas un autre zombie
    run(w, HIT_COOLDOWN + DT)
    w._teleport(z, (500, 400))
    hp = z.hp
    w.hit(h)
    assert z.hp == hp


def test_respawning_zombie_is_invulnerable_and_harmless():
    w = empty_world()
    h, z = zombie_target(w)
    z.hp = BULLET_DAMAGE
    w.shoot(h)
    assert z.respawn_until > w.now
    w._teleport(h, (z.x + 10, z.y))              # collé à lui pendant la réapparition
    w._infection()
    assert h.role == HUMAN
    hp = z.hp
    w._damage_zombie(z, 50, h)
    assert z.hp == hp
    run(w, RESPAWN_TIME + 0.1)
    assert w.now >= z.frozen_until


def test_zombies_cannot_shoot_and_reload_works():
    w = empty_world()
    z, h = w.add_player("Z"), w.add_player("H")
    w._set_role(z, ZOMBIE)
    assert not w.shoot(z)
    for _ in range(MAG_SIZE):
        assert w.shoot(h)
        run(w, 0.4)
    assert h.ammo == 0 and h.reload_t > 0 and not w.shoot(h)
    run(w, 2.1)
    assert h.ammo == MAG_SIZE and w.shoot(h)


# ----------------------------------------------------------- manche et règles
def test_round_flow_wait_intermission_play():
    w = empty_world()
    w.add_player("A")
    run(w, 1)
    assert w.phase == "wait"
    w.add_player("B")
    run(w, 0.2)
    assert w.phase == "intermission"
    run(w, w.cfg.intermission_seconds + 0.5)
    assert w.phase == "play"
    assert len(w.zombies()) == 1 and len(w.humans()) == 1


def test_patient_zero_is_frozen_then_released():
    w = empty_world(freeze_seconds=5)
    start_round(w)
    z = w.zombies()[0]
    z.dx = 1
    x0 = z.x
    run(w, 3)
    assert abs(z.x - x0) < 1
    assert w.snapshot()["fz"] > 0
    run(w, 3)
    assert abs(z.x - x0) > 20


def test_infection_on_contact_and_zombies_win():
    w = empty_world(freeze_seconds=0)
    start_round(w)
    z, h = w.zombies()[0], w.humans()[0]
    w._teleport(z, (500, 400))
    w._teleport(h, (500 + INFECT_DIST - 3, 400))
    w.step(DT)
    assert h.role == ZOMBIE and h.shape.filter.categories == CAT_ZOMBIE
    assert w.phase == "end" and w.winner == "zombies"
    assert any(e["k"] == "infect" for e in w.snapshot()["ev"])


def test_frozen_patient_zero_cannot_infect():
    w = empty_world(freeze_seconds=10)
    start_round(w)
    z, h = w.zombies()[0], w.humans()[0]
    w._teleport(z, (500, 400))
    w._teleport(h, (500 + INFECT_DIST - 3, 400))
    w.step(DT)
    assert h.role == HUMAN


def test_humans_win_when_timer_ends():
    w = empty_world(round_seconds=5, freeze_seconds=0)
    ps = start_round(w, 3)
    for p in ps:
        w._teleport(p, (200 + 400 * ps.index(p), 1400))   # loin les uns des autres
    # on fige les zombies pour ne tester que le timer
    for z in w.zombies():
        z.frozen_until = 1e9
    run(w, 6)
    assert w.phase == "end" and w.winner == "humans"


def test_round_restarts_with_fresh_roles_and_props():
    w = World(Settings(round_seconds=3, freeze_seconds=0, end_seconds=1, intermission_seconds=1), seed=7)
    pr = next(iter(w.props.values()))
    home = pr.home
    w.add_player("A")
    w.add_player("B")
    while w.phase != "end":
        w.step(DT)
        assert w.now < 30, "la manche n'a jamais pris fin"
    assert w.winner in ("humans", "zombies")
    pr.body.position = (home[0] + 100, home[1])       # on déplace un meuble pendant l'écran de fin
    while w.phase != "intermission":
        w.step(DT)
    assert math.hypot(pr.body.position.x - home[0], pr.body.position.y - home[1]) < 5   # remis en place
    assert all(p.role == HUMAN for p in w.players.values())                              # tout le monde humain


def test_player_joining_mid_round_becomes_zombie():
    w = empty_world(freeze_seconds=0)
    start_round(w, 3)
    late = w.add_player("Late")
    assert late.role == ZOMBIE


def test_zombie_leaving_promotes_a_human():
    w = empty_world(freeze_seconds=0)
    start_round(w, 3)
    z = w.zombies()[0]
    w.remove_player(z.id)
    assert len(w.zombies()) == 1


def test_round_cancelled_if_too_few_players():
    w = empty_world()
    a, _ = start_round(w)
    w.remove_player(a.id)
    run(w, 0.2)
    assert w.phase == "end" and w.winner == "none"


def test_24_players_max_and_sanitized_names():
    w = empty_world()
    for i in range(24):
        w.add_player(f"P{i}")
    assert not w.can_join()
    assert empty_world().add_player("  \x00\x07Zoé  ").name == "Zoé"
    assert len(empty_world().add_player("x" * 100).name) == 16


def test_snapshot_only_contains_changed_props():
    w = World(seed=7)
    w.add_player("A")
    w.snapshot()
    w.step(DT)
    w.snapshot()                    # purge des envois initiaux
    w.step(DT)
    assert w.snapshot()["pr"] == []
    pr = next(iter(w.props.values()))
    pr.body.velocity = (300, 0)
    w.step(DT)
    changed = [e[0] for e in w.snapshot()["pr"]]
    assert pr.id in changed and len(changed) < 5


# --------------------------------------------------------------------- bots
def test_zombie_bot_finds_a_human_in_another_room():
    w = World(Settings(freeze_seconds=0, fill_to=2), seed=7)
    real = w.add_player("Humain")          # + 1 bot
    run(w, w.cfg.intermission_seconds + 0.5)
    assert w.phase == "play"
    zombie = w.zombies()[0]
    human = w.humans()[0]
    if zombie.bot is None:                 # le patient zéro est le vrai joueur : on inverse les rôles
        w._set_role(zombie, HUMAN)
        w._set_role(human, ZOMBIE)
        zombie, human = human, zombie
    w._teleport(human, (200, 1300))        # pièce du bas à gauche, zombie en haut à droite
    human.dx = human.dy = 0
    while w.phase == "play" and w.now < 90:
        w.step(DT)
    assert w.phase == "end" and w.winner == "zombies", f"phase={w.phase} t={w.now:.0f}"
    assert real is not None


def test_path_reaches_a_player_wedged_in_a_wall_corner():
    """Joueur collé à l'angle de deux murs (sa case de navigation est « bloquée ») : on trouve quand même."""
    w = empty_world()
    assert w.nav.cell_of(832, 831) in w.nav.blocked     # coin des murs x=800 / y=800 du manoir
    assert w.nav.path((1300, 300), (832, 831))


def bare_world(name):
    w = World(Settings(map=name, intermission_seconds=999), seed=7)
    for pr in list(w.props.values()):
        w.space.remove(pr.body, pr.shape)
    w.props.clear()
    return w


def reached(z, h):
    return math.hypot(z.x - h.x, z.y - h.y) < 2 * PLAYER_R + 6


def chase(w, z, h, seconds):
    """Hors manche (entracte) il n'y a pas d'infection : on regarde si le zombie arrive au contact."""
    for _ in range(int(seconds / DT)):
        w.step(DT)
        if reached(z, h):
            return True
    return False


@pytest.mark.parametrize(("name", "target"), [("manoir", (400, 400)), ("entrepot", (3050, 600))])
def test_zombie_bot_does_not_get_stuck_on_door_frames(name, target):
    """Cas qui bloquaient : angle de porte du manoir, bout du couloir central de l'entrepôt."""
    w = bare_world(name)
    h = w.add_player("H")
    z = w.add_player("Z", bot=True)
    w._set_role(z, ZOMBIE)
    zx0, zy0, zx1, zy1 = w.map.rooms[w.map.zombie_room]
    w._teleport(z, ((zx0 + zx1) / 2, (zy0 + zy1) / 2))
    w._teleport(h, target)
    h.frozen_until = 1e9
    assert chase(w, z, h, 30)


def test_zombie_bot_targets_the_nearest_human_by_corridors_not_as_the_crow_flies():
    """Entrepôt : A est juste derrière le mur (proche à vol d'oiseau, loin par les couloirs), B est l'inverse."""
    w = bare_world("entrepot")
    a = w.add_player("A")
    b = w.add_player("B")
    z = w.add_player("Z", bot=True)
    w._set_role(z, ZOMBIE)
    w._teleport(z, (1650, 200))     # pièce du haut en cul-de-sac (seule sortie : porte en x=1300)
    w._teleport(a, (1650, 600))     # couloir central, 400 px sous le zombie mais ~1500 px par les portes
    w._teleport(b, (800, 300))      # pièce voisine, ~850 px à vol d'oiseau et à peu près autant à pied
    a.frozen_until = b.frozen_until = 1e9
    for _ in range(int(20 / DT)):
        w.step(DT)
        if reached(z, a) or reached(z, b):
            break
    assert reached(z, b) and not reached(z, a)


def test_distance_field_is_shared_and_refreshed_at_most_4_times_per_second(monkeypatch):
    w = bare_world("manoir")
    w.add_player("H")
    for i in range(6):
        z = w.add_player(f"Z{i}", bot=True)
        w._set_role(z, ZOMBIE)
    calls = []
    real = w.nav.distance_field
    monkeypatch.setattr(w.nav, "distance_field", lambda src: calls.append(1) or real(src))
    run(w, 2)
    assert 0 < len(calls) <= 2 / FLOW_REFRESH + 1


def test_bots_fill_and_leave():
    w = World(Settings(fill_to=8), seed=7)
    p = w.add_player("A")
    assert len(w.players) == 8
    w.remove_player(p.id)
    assert len(w.players) == 0
