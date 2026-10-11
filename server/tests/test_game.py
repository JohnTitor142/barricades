import dataclasses
import math

import pymunk
import pytest

import app.game as game_mod
from app.game import (
    ALPHA_R,
    BULLET_DAMAGE,
    CAT_WALL,
    CAT_ZOMBIE,
    DASH_COOLDOWN,
    FALLOFF_MIN,
    FLOW_REFRESH,
    HIT_COOLDOWN,
    HUMAN,
    INFECT_DIST,
    MAG_SIZE,
    MELEE_DAMAGE,
    PICKUP_COUNT,
    PICKUP_RESPAWN,
    PLAYER_R,
    PROP_KINDS,
    RAGE_COOLDOWN,
    RAGE_TIME,
    RESPAWN_TIME,
    WEAPONS,
    ZOMBIE,
    ZOMBIE_HP,
    ZOMBIE_SPEED,
    NavGrid,
    Settings,
    World,
    falloff,
)
from app.maps import MAPS, cut_doors

DT = 1 / 30


def empty_world(**kw) -> World:
    """Monde sans meubles : pour isoler une règle."""
    w = World(Settings(**kw), seed=7)
    for pr in list(w.props.values()):
        w.space.remove(pr.body, *pr.shapes)
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
    start = w.map.areas[w.map.zombie_areas[0]].inner_point()
    for a in w.map.areas:
        assert w.nav.path(start, a.inner_point()), a.id
    for dx, dy in w.doors:
        assert w._free(dx, dy, PLAYER_R + 4), (dx, dy)
    assert not w.map.unused_doors, w.map.unused_doors      # chaque porte perce bien un mur
    assert w.map.zombie_areas and w.map.human_areas
    for i in w.map.human_areas + w.map.zombie_areas:      # on peut apparaître partout où c'est prévu
        assert w.map.areas[i].random_point(w.rng, margin=PLAYER_R + 20), w.map.areas[i].id


def test_doors_leave_exactly_the_requested_opening():
    """Un mur horizontal de 400 px percé d'une porte de 110 : deux tronçons, 110 px de vide entre leurs bords."""
    walls, unused = cut_doors([((0, 0), (400, 0), 24, "brick")], [(200, 0, 110)])
    assert not unused and len(walls) == 2
    a, b = sorted(walls, key=lambda wl: wl.x1)
    assert (b.x1 - b.t / 2) - (a.x2 + a.t / 2) == 110      # bords arrondis compris


def test_oblique_walls_block_players_and_navigation():
    """Mur en diagonale (45°) : on ne le traverse pas, et la navigation le contourne."""
    w = empty_world()
    from app.maps import Wall
    diag = Wall(600, 200, 1000, 600, 24, "stone")
    seg = pymunk.Segment(w.space.static_body, (diag.x1, diag.y1), (diag.x2, diag.y2), diag.t / 2)
    seg.filter = pymunk.ShapeFilter(categories=CAT_WALL)
    w.space.add(seg)
    nav = NavGrid([*w.walls, diag], w.map.w, w.map.h)
    assert nav.is_blocked(nav.cell_of(800, 400))           # milieu du mur
    p = w.add_player("A")
    w._teleport(p, (700, 500))                            # sous la diagonale
    w.set_input(p.id, 0.7071, -0.7071, 0)                 # fonce perpendiculairement au mur
    run(w, 2)
    assert p.y - (p.x - 400) > 0                          # toujours du même côté de la droite y = x - 400


def test_unknown_map_is_refused():
    with pytest.raises(ValueError):
        World(Settings(map="atlantide"))


def test_zombie_bot_crosses_the_long_map():
    """Sur l'entrepôt, un bot zombie part de sa salle (à gauche) et rejoint un humain dans la salle finale."""
    w = World(Settings(map="entrepot", fill_to=0, intermission_seconds=999), seed=3)   # pas de manche : rôles figés
    for pr in list(w.props.values()):          # sans meubles : on teste la navigation, pas la casse
        w.space.remove(pr.body, *pr.shapes)
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


def test_zombie_hits_break_a_prop_and_free_the_way():
    w = empty_world()
    pr = w._add_prop("chair", 400, 400, 0)
    z = w.add_player("Z")
    w._set_role(z, ZOMBIE)
    w._teleport(z, (360, 400))
    z.aim = 0
    hp = PROP_KINDS["chair"].hp
    for i in range(hp):
        assert not pr.broken and pr.hp == hp - i
        pr.body.position, pr.body.velocity = (400, 400), (0, 0)   # une chaise vole loin : on la remet devant
        w.space.reindex_shapes_for_body(pr.body)
        hit_n(w, z, 1)
    assert pr.broken and not set(pr.shapes) & set(w.space.shapes)
    assert any(e["k"] == "break" and e["id"] == pr.id for e in w.snapshot()["ev"])


def test_humans_push_props_but_never_damage_them():
    w = empty_world()
    pr = w._add_prop("wardrobe", 400, 400, 0)
    h = w.add_player("H")
    w._teleport(h, (330, 400))
    h.aim = 0
    hit_n(w, h, 3)
    assert pr.hp == pr.max_hp and pr.body.position.x > 400


def test_props_take_20_to_50_zombie_hits_heavier_ones_more():
    hps = {k: v.hp for k, v in PROP_KINDS.items()}
    assert all(20 <= hp <= 50 for hp in hps.values())
    assert hps["piano"] > hps["table"] > hps["chair"]


def test_multi_part_prop_is_one_body_and_takes_one_hit_per_blow():
    """Piano à queue (clavier + caisse) : deux formes, un seul corps, un seul coup compté par frappe."""
    w = empty_world()
    pr = w._add_prop("piano", 400, 400, 0)
    assert len(pr.shapes) == 2 and all(sh.body is pr.body for sh in pr.shapes)
    z = w.add_player("Z")
    w._set_role(z, ZOMBIE)
    w._teleport(z, (400, 330))                     # au-dessus de la jonction clavier / caisse
    z.aim = math.pi / 2
    assert w.hit(z)
    assert pr.hp == pr.max_hp - 1


def test_round_props_roll_and_block_like_the_others():
    w = empty_world()
    barrel = w._add_prop("barrel", 400, 400, 0)
    p = w.add_player("A")
    w._teleport(p, (330, 400))
    w.set_input(p.id, 1, 0, 0)
    for _ in range(int(2 / DT)):
        w.step(DT)                                  # léger : il glisse devant nous, mais on ne le traverse jamais
        bx, by = barrel.body.position
        assert math.hypot(p.x - bx, p.y - by) > 22 + PLAYER_R - 4    # (tolérance de contact pymunk)


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
    assert not pr.broken and pr.hp == pr.max_hp and pr.shapes[0] in w.space.shapes
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
    wall.hp = 6                                   # vrai lit : 45 coups ; on raccourcit (après l'arrivée des joueurs,
    run(w, 25)                                    # qui remet les meubles à neuf) : c'est le mécanisme qu'on teste
    assert wall.broken
    assert math.hypot(z.x - h.x, z.y - h.y) < 120


def test_hit_cooldown():
    w = empty_world()
    p = w.add_player("A")
    assert w.hit(p) and not w.hit(p)
    run(w, 0.6)
    assert w.hit(p)


# -------------------------------------------------------------------- tir
@pytest.fixture
def no_spread(monkeypatch):
    """Tirs parfaitement précis : pour tester poussée, ralentissement, tir ami... sans le hasard de la dispersion."""
    precise = {k: dataclasses.replace(v, spread=0.0, bloom=0.0, bloom_max=0.0) for k, v in WEAPONS.items()}
    monkeypatch.setattr(game_mod, "WEAPONS", precise)


def test_shot_pushes_prop_and_costs_ammo(no_spread):
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


def test_bullets_pass_through_friends(no_spread):
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


def test_shot_hits_zombie_and_slows_it(no_spread):
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


def test_bullets_eventually_kill_a_zombie_who_respawns_in_his_room(no_spread):
    w = empty_world(intermission_seconds=999)      # ~20 s de tir : pas de nouvelle manche (qui changerait les rôles)
    h, z = zombie_target(w)
    shots = 0
    while not any(e["k"] == "kill" for e in w.events):
        w._teleport(z, (500, 400))               # le recul l'éloigne : on le remet en place
        z.kbx = z.kby = 0.0
        if w.shoot(h):
            shots += 1
        run(w, 0.4)
        assert shots <= 2 * ZOMBIE_HP / BULLET_DAMAGE
    assert shots == math.ceil(ZOMBIE_HP / BULLET_DAMAGE)       # tirs précis (no_spread), à courte portée
    assert any(w.map.areas[i].contains(z.x, z.y) for i in w.map.zombie_areas) and z.hp == ZOMBIE_HP
    assert w.snapshot()["p"][1][5] & 4            # drapeau « en réapparition »


def zombie_line(n=1, x=300, y=400, distance=200):
    w = empty_world(intermission_seconds=999)
    h = w.add_player("H")
    w._teleport(h, (x, y))
    h.aim = 0
    zs = []
    for i in range(n):
        z = w.add_player(f"Z{i}")
        w._set_role(z, ZOMBIE)
        w._teleport(z, (x + distance, y))
        zs.append(z)
    return w, h, zs


def hits_out_of(w, h, z, shots, distance):
    """Proportion de balles qui touchent un zombie immobile à `distance` (repositionné à chaque tir)."""
    hits = 0
    for _ in range(shots):
        run(w, WEAPONS[h.weapon].cooldown + 0.6)   # assez de pause pour que la dispersion retombe
        h.reload_t, h.ammo = 0.0, 5
        w._teleport(z, (h.x + distance, h.y))
        z.kbx = z.kby = 0.0
        w.events.clear()
        w.shoot(h)
        hits += any(e["k"] == "shot" and e["h"] == "zombie" for e in w.events)
    return hits / shots


def test_shots_spread_randomly_and_miss_more_at_long_range():
    w, h, (z,) = zombie_line()
    z.frozen_until = 1e9                           # invulnérable : on mesure la précision, pas les dégâts
    near = hits_out_of(w, h, z, 40, 150)
    far = hits_out_of(w, h, z, 40, 850)
    assert near >= 0.9 and far < 0.7 and far < near


def test_damage_falls_off_with_distance():
    assert falloff(100, 900) == 1.0
    assert falloff(900, 900) == FALLOFF_MIN
    assert 1.0 > falloff(560, 900) > FALLOFF_MIN


def test_spraying_widens_the_spread_then_it_recovers():
    w, h, _ = zombie_line()
    h.ammo = 6
    for _ in range(4):
        h.shot_cd = 0.0
        w.shoot(h)
    sprayed = h.bloom
    assert sprayed > WEAPONS["pistol"].bloom * 2
    run(w, 1)
    assert h.bloom < sprayed / 2


def test_mp9_fires_much_faster_than_the_pistol_and_shotgun_fires_pellets():
    assert WEAPONS["mp9"].cooldown < WEAPONS["pistol"].cooldown / 3
    assert WEAPONS["mp9"].mag > WEAPONS["pistol"].mag
    w, h, _ = zombie_line()
    w.give_weapon(h, "shotgun")
    w.events.clear()
    assert w.shoot(h)
    assert sum(e["k"] == "shot" for e in w.events) == WEAPONS["shotgun"].pellets


def test_weapons_on_the_ground_are_picked_up_by_humans_only_and_come_back():
    w = World(Settings(intermission_seconds=0.5, freeze_seconds=0), seed=7)
    h, z = start_round(w, 2)
    if h.role == ZOMBIE:
        h, z = z, h
    assert len(w.pickups_list()) == PICKUP_COUNT and h.weapon == "pistol"
    pk = next(iter(w.pickups.values()))
    w._teleport(z, (pk.x, pk.y))                   # un zombie ne ramasse rien
    run(w, 0.2)
    assert pk.respawn_at == 0 and z.weapon == "pistol"
    w._teleport(z, (100, 100))
    w._teleport(h, (pk.x, pk.y))
    run(w, 0.2)
    assert h.weapon == pk.kind and h.ammo == WEAPONS[pk.kind].mag and pk.respawn_at > 0
    assert len(w.pickups_list()) == PICKUP_COUNT - 1
    assert any(e["k"] == "pickup" for e in w.snapshot()["ev"])
    run(w, PICKUP_RESPAWN + 0.5)
    assert pk.respawn_at == 0                     # revenue (ailleurs)


def test_zombie_hint_points_to_the_door_not_through_the_wall():
    """Manoir : humain juste derrière le mur x=800, la porte est en (800, 360). La flèche vise la porte."""
    w = empty_world(intermission_seconds=999)
    z = w.add_player("Z")
    h = w.add_player("H")
    w._set_role(z, ZOMBIE)
    w._teleport(z, (700, 700))
    w._teleport(h, (900, 700))                     # à 200 px, mais derrière le mur
    a = w.zombie_hint(z)
    to_door = math.atan2(360 - 700, 800 - 700)
    straight = 0.0
    assert abs(a - to_door) < abs(a - straight)
    assert w.zombie_hint(h) is None and w.me(h.id)[3] is None
    assert w.me(z.id)[2] == "pistol" and isinstance(w.me(z.id)[3], float)


def test_zombie_dash_leaps_forward_then_recharges_in_10_s():
    w = empty_world(intermission_seconds=999)
    z, h = w.add_player("Z"), w.add_player("H")
    w._set_role(z, ZOMBIE)
    w._teleport(z, (500, 400))
    w.set_input(z.id, 1, 0, 0)
    run(w, 0.5)
    x0 = z.x
    assert w.dash(z)
    run(w, 0.5)
    dashed = z.x - x0
    assert dashed > ZOMBIE_SPEED * 0.5 + 100          # ~150 px de plus qu'en marchant
    assert not w.dash(z) and not w.dash(h)            # en recharge ; un humain ne dashe pas
    run(w, DASH_COOLDOWN)
    assert w.dash(z)
    assert any(e["k"] == "dash" for e in w.events)


def test_patient_zero_is_a_bigger_faster_alpha_and_stays_alpha_after_dying():
    w = empty_world(intermission_seconds=0.5, freeze_seconds=0)
    a, b = start_round(w, 2)
    alpha, human = (a, b) if a.role == ZOMBIE else (b, a)
    assert alpha.alpha and not human.alpha
    assert alpha.shape.radius == ALPHA_R > PLAYER_R
    assert w.snapshot()["p"][[p.id for p in w.players.values()].index(alpha.id)][5] & 8
    w._teleport(alpha, (300, 300))
    w._teleport(human, (1300, 300))
    human.frozen_until = 1e9
    w.set_input(alpha.id, 1, 0, 0)
    run(w, 0.5)                                       # lancé (le démarrage coûte quelques px)
    x0 = alpha.x
    run(w, 1)
    assert alpha.x - x0 > ZOMBIE_SPEED * 1.08         # plus rapide qu'un zombie normal
    alpha.hp = 1
    w._damage_zombie(alpha, 5, human)                 # abattu : réapparaît, toujours alpha
    assert alpha.alpha and alpha.respawn_until > w.now


def test_alpha_infects_from_further_away_because_it_is_bigger():
    w = empty_world(intermission_seconds=0.5, freeze_seconds=0)
    z, h = w.add_player("Z"), w.add_player("H")
    run(w, 1)
    w._set_role(z, ZOMBIE)
    w._set_role(h, HUMAN)
    w._set_alpha(z, True)
    w._teleport(z, (500, 400))
    w._teleport(h, (500 + INFECT_DIST + 4, 400))      # hors de portée d'un zombie normal
    z.frozen_until = 0
    w._infection()
    assert h.role == ZOMBIE


def test_alpha_rage_ignores_bullet_slow_for_5_s_and_recharges_in_30_s(no_spread):
    w, h, (z,) = zombie_line()
    assert not w.rage(z)                              # pas alpha : pas de sort
    w._set_alpha(z, True)
    assert w.rage(z)
    w.shoot(h)
    assert z.slow_until <= w.now and z.hp < ZOMBIE_HP # touché, mais pas ralenti
    assert not w.rage(z)                              # en recharge
    run(w, RAGE_TIME + 0.2)
    h.shot_cd = h.reload_t = 0.0
    h.ammo = 6
    w._teleport(z, (h.x + 200, h.y))
    w.shoot(h)
    assert z.slow_until > w.now                       # sort terminé : ralenti de nouveau
    run(w, RAGE_COOLDOWN)
    assert w.rage(z)


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
    assert w.nav.is_blocked(w.nav.cell_of(832, 831))    # coin des murs x=800 / y=800 du manoir
    assert w.nav.path((1300, 300), (832, 831))


def bare_world(name):
    w = World(Settings(map=name, intermission_seconds=999), seed=7)
    for pr in list(w.props.values()):
        w.space.remove(pr.body, *pr.shapes)
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
    w._teleport(z, w.map.areas[w.map.zombie_areas[0]].inner_point())
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


def test_full_room_of_24_bots_still_lets_real_players_in():
    w = World(Settings(fill_to=24), seed=7)
    w.add_player("Moi")
    assert len(w.players) == 24 and w.real_count == 1
    assert w.can_join()
    w.add_player("Ami")                            # un bot lui cède sa place
    assert len(w.players) == 24 and w.real_count == 2


def test_last_player_leaving_mid_round_leaves_no_ghost_events_for_the_next_one():
    """Le dernier vrai joueur part en pleine manche : les bots s'en vont sans désigner de patient zéro
    fantôme, et le joueur suivant ne reçoit aucun événement périmé."""
    w = World(Settings(fill_to=8, intermission_seconds=0.5, freeze_seconds=0), seed=7)
    me = w.add_player("Moi")
    run(w, 1)
    assert w.phase == "play"
    w.snapshot()
    w.remove_player(me.id)
    assert not w.players and not any(e["k"] == "zero" for e in w.events)
    w.add_player("Suivant")
    assert w.snapshot()["ev"] == []


def test_bots_fill_and_leave():
    w = World(Settings(fill_to=8), seed=7)
    p = w.add_player("A")
    assert len(w.players) == 8
    w.remove_player(p.id)
    assert len(w.players) == 0
