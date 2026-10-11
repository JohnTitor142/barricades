import Phaser from 'phaser';
import { sound } from '../audio.js';
import { drawKind, kindBounds, randomPointIn, styleOf } from '../furniture.js';
import { Minimap, minimapDots } from '../minimap.js';
import { INTERP_DELAY, net } from '../net.js';

// Sols, murs et obstacles par type (les cartes viennent du serveur ; un type inconnu reste lisible).
const GROUND = {
  floor: 0x15120f, wood: 0x1d150e, tile: 0x16181b, carpet: 0x1b0f13, stone: 0x1a1918, straw: 0x251f10,
  concrete: 0x161616, grass: 0x0e160b, asphalt: 0x0f0f11, sidewalk: 0x24221f, dirt: 0x211810,
  field: 0x18200c, gravel: 0x1f1e1a, cemetery: 0x101410,
};
const WALL = {
  brick: [0x6a3f33, 0x2a1712], wood: [0x5a4430, 0x22180e], stone: [0x6a6862, 0x262522],
  concrete: [0x4a4742, 0x1a1917], fence: [0x7a6442, 0x2a2214], iron: [0x6a6a72, 0x141417],
  hedge: [0x1f3d1b, 0x0b1609], grave: [0x7a7a80, 0x2a2a2e],
};
const OBSTACLE = {
  tree: [0x173315, 0x0a1709], rock: [0x55534e, 0x22211f], well: [0x4a4a55, 0x15151a],
  silo: [0x8a8a8a, 0x3a3a3a], pillar: [0x4a4742, 0x1a1917], pump: [0x8a1e1e, 0x2a0a0a],
};
const HUMAN = 0;
const ZOMBIE_BODY = 0x7ea35c;
const BLOODS = [0x6e0f16, 0x8b1a22, 0x540b10];
const WEAPON_LABEL = { pistol: 'PISTOLET', mp9: 'MP9', shotgun: 'POMPE' };
const GUN_LENGTH = { pistol: 30, mp9: 34, shotgun: 40 };
// Plafonds pour que le coût d'affichage reste borné même en fin de manche longue.
const MAX_SHOT_SPLATS = 300; // taches d'impact de balle par manche (les infections passent toujours)
const MAX_FX = 48;           // traînées de balle / coups affichés en même temps

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export class GameScene extends Phaser.Scene {
  constructor() {
    super('game');
  }

  create() {
    this.built = -1;
    this.propObjs = new Map();
    this.labels = new Map();
    this.fx = [];
    this.shotSplats = 0;
    this.lastShotSound = new Map();
    this.lastPhase = null;
    this.lastSend = 0;
    this.lastFire = 0;
    this.lastHud = 0;
    this.firing = false;

    this.cameras.main.setBackgroundColor('#030403');
    this.floorChunks = [];
    this.minimap = new Minimap(document.getElementById('minimap'), window.innerWidth < 700 ? 130 : 220);
    // Le sang est « cuit » dans une texture : chaque tache est dessinée une seule fois,
    // puis la texture s'affiche d'un bloc. Le coût par image ne dépend plus du nombre de taches.
    this.blood = null;
    this.splatBrush = this.make.graphics({}, false); // pinceau hors scène
    this.pg = this.add.graphics().setDepth(4);
    this.fxg = this.add.graphics().setDepth(6);
    this.makeDarkness();

    this.input.mouse?.disableContextMenu();
    this.input.keyboard.disableGlobalCapture(); // ne pas bloquer la saisie du nom
    this.keys = this.input.keyboard.addKeys('Z,Q,S,D,W,A,UP,DOWN,LEFT,RIGHT');
    this.input.keyboard.on('keydown-SPACE', () => net.sendAct('hit'));
    this.input.on('pointerdown', (p) => {
      if (p.rightButtonDown()) net.sendAct('hit');
      else this.firing = true;
    });
    this.input.on('pointerup', () => { this.firing = false; });

    net.on((ev) => this.onNetEvent(ev));

    this.hud = {
      root: document.getElementById('hud'),
      timer: document.getElementById('timer'),
      humans: document.getElementById('c-humans'),
      zombies: document.getElementById('c-zombies'),
      banner: document.getElementById('banner'),
      role: document.getElementById('role'),
      ammo: document.getElementById('ammo'),
    };
  }

  // ------------------------------------------------------------ ambiance
  makeDarkness() {
    const tex = this.textures.createCanvas('dark', 1024, 1024);
    const ctx = tex.getContext();
    const g = ctx.createRadialGradient(512, 512, 0, 512, 512, 512);
    g.addColorStop(0, 'rgba(0,0,0,0)');
    g.addColorStop(0.12, 'rgba(0,0,0,0)');
    g.addColorStop(0.3, 'rgba(0,0,0,0.8)');
    g.addColorStop(1, 'rgba(0,0,0,0.95)');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 1024, 1024);
    tex.refresh();
    this.dark = this.add.image(0, 0, 'dark').setScrollFactor(0).setDepth(50);
  }

  // ------------------------------------------------------------ construction
  build() {
    this.built = net.session;
    for (const o of this.propObjs.values()) o.destroy();
    this.propObjs.clear();

    const { w, h } = net.world;
    this.blood?.destroy();
    this.blood = this.add.renderTexture(0, 0, w, h).setOrigin(0).setDepth(1);
    this.shotSplats = 0;
    // Le décor (sols, murs, obstacles) ne bouge jamais : on le dessine UNE fois dans des textures découpées en
    // tuiles (≤ 2048 px, accepté par toutes les cartes graphiques). Redessiné à chaque image, il coûtait ~18 ms.
    const f = this.make.graphics({}, false);
    f.fillStyle(GROUND[net.base] ?? GROUND.floor, 1);
    f.fillRect(0, 0, w, h);
    for (const [ground, poly] of net.areas) {
      f.fillStyle(GROUND[ground] ?? GROUND.floor, 1);
      f.fillPoints(poly.map(([x, y]) => ({ x, y })), true);
    }
    f.lineStyle(1, 0x000000, 0.3);           // trame légère (lattes, dalles, sillons)
    for (let x = 0; x <= w; x += 80) f.lineBetween(x, 0, x, h);
    for (let y = 0; y <= h; y += 80) f.lineBetween(0, y, w, y);
    // Murs : segments épais à bouts ronds, à n'importe quel angle (contour sombre, puis couleur du style).
    for (const pass of [1, 0]) {
      for (const [x1, y1, x2, y2, t, style] of net.walls) {
        const col = (WALL[style] ?? WALL.concrete)[pass];
        const tt = t + (pass ? 4 : 0);
        f.lineStyle(tt, col, 1);
        f.lineBetween(x1, y1, x2, y2);
        f.fillStyle(col, 1);
        f.fillCircle(x1, y1, tt / 2);
        f.fillCircle(x2, y2, tt / 2);
      }
    }
    for (const [kind, x, y, r] of net.obstacles) {
      const [fill, edge] = OBSTACLE[kind] ?? OBSTACLE.rock;
      f.fillStyle(edge, 1);
      f.fillCircle(x, y, r + 2);
      f.fillStyle(fill, 1);
      f.fillCircle(x, y, r);
      if (kind === 'tree') {                 // feuillage : quelques touffes plus claires
        f.fillStyle(0x234a1f, 1);
        for (let i = 0; i < 5; i++) f.fillCircle(x + Math.cos(i * 1.3) * r * 0.45, y + Math.sin(i * 1.3) * r * 0.45, r * 0.35);
      } else if (kind === 'well' || kind === 'silo') {
        f.lineStyle(3, edge, 1);
        f.strokeCircle(x, y, r * 0.6);
      }
    }
    for (const rt of this.floorChunks) rt.destroy();
    this.floorChunks = [];
    const TILE = 2048;
    for (let x0 = 0; x0 < w; x0 += TILE) {
      for (let y0 = 0; y0 < h; y0 += TILE) {
        const rt = this.add.renderTexture(x0, y0, Math.min(TILE, w - x0), Math.min(TILE, h - y0));
        rt.setOrigin(0).setDepth(0);
        rt.draw(f, -x0, -y0);
        this.floorChunks.push(rt);
      }
    }
    f.destroy();
    const mapH = this.minimap.build(net);
    document.getElementById('feed').style.top = `${mapH + 26}px`;   // le fil d'événements passe sous la mini-carte

    // Une texture par type de meuble (dessinée une fois), partagée par tous les meubles de ce type.
    const brush = this.make.graphics({}, false);
    const tex = {};
    for (const [kind, parts] of Object.entries(net.kinds)) {
      const key = `prop_${kind}`;
      if (this.textures.exists(key)) this.textures.remove(key);
      tex[kind] = drawKind(brush, kind, parts);
      brush.generateTexture(key, tex[kind].w, tex[kind].h);
    }
    brush.destroy();

    for (const [id, info] of net.propInfo) {
      const t = tex[info.kind];
      if (!t) continue;
      const c = this.add.container(0, 0).setDepth(2);
      c.img = this.add.image(0, 0, `prop_${info.kind}`).setOrigin(t.originX, t.originY);
      c.cracks = this.add.graphics();
      c.add([c.img, c.cracks]);
      c.parts = net.kinds[info.kind];
      c.info = info;
      c.pid = id;
      c.pct = 100;
      this.propObjs.set(id, c);
    }
  }

  // ------------------------------------------------------------ événements
  onNetEvent(ev) {
    const now = performance.now();
    if (ev.k === 'shot') {
      // Fusil à pompe : 7 plombs = 7 événements dans le même instant ; un seul son par décharge.
      const last = this.lastShotSound.get(ev.id) ?? -1e9;
      if (now - last > 60) sound.shot(ev.x1, ev.y1, ev.w);
      this.lastShotSound.set(ev.id, now);
      this.addFx({ k: 'tracer', ev, until: now + 90 });
      if (ev.h === 'zombie' && this.shotSplats < MAX_SHOT_SPLATS) {
        this.shotSplats += 1;
        this.splat(ev.x2, ev.y2, 4, 10);
      }
    } else if (ev.k === 'hit') {
      sound.hit(ev.x, ev.y, ev.n > 0);
      this.addFx({ k: 'swing', ev, until: now + 150 });
    } else if (ev.k === 'pickup') {
      if (ev.id === net.id) sound.pickup();
    } else if (ev.k === 'break') {
      sound.crash(ev.x, ev.y);
      const info = net.propInfo.get(ev.id);
      if (info) this.debris(ev.x, ev.y, info);
    } else if (ev.k === 'kill') {
      sound.death(ev.x, ev.y);
      this.splat(ev.x, ev.y, 22, 46);
    } else if (ev.k === 'infect') {
      this.splat(ev.x, ev.y, 14, 38);
    }
  }

  addFx(f) {
    if (this.fx.length >= MAX_FX) this.fx.shift(); // on sacrifie le plus ancien
    this.fx.push(f);
  }

  splat(x, y, n, spread) {
    if (!this.blood) return; // pas encore de carte (événement reçu avant le premier affichage)
    const g = this.splatBrush;
    g.clear();
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const d = Math.random() * spread;
      g.fillStyle(BLOODS[i % BLOODS.length], 0.85);
      g.fillCircle(x + Math.cos(a) * d, y + Math.sin(a) * d, 2 + Math.random() * 5);
    }
    this.blood.draw(g);
  }

  /** Débris d'un meuble cassé, « cuits » au sol comme le sang (effacés à la manche suivante). */
  debris(x, y, info) {
    if (!this.blood) return;
    const [side, top] = styleOf(info.kind);
    const g = this.splatBrush;
    const [x0, y0, x1, y1] = kindBounds(net.kinds[info.kind] ?? [['box', 40, 40, 0, 0]]);
    const spread = Math.max(x1 - x0, y1 - y0) * 0.6;
    g.clear();
    for (let i = 0; i < 18; i++) {
      const a = Math.random() * Math.PI * 2;
      const d = Math.random() * spread;
      const s = 3 + Math.random() * 9;
      g.fillStyle(i % 3 ? side : top, 0.9);
      g.fillRect(x + Math.cos(a) * d - s / 2, y + Math.sin(a) * d - s / 4, s, s / 2);
    }
    this.blood.draw(g);
  }

  /** Fissures de plus en plus nombreuses quand les PV baissent ; caché une fois cassé. */
  setPropDamage(obj, pct) {
    obj.pct = pct;
    obj.setVisible(pct > 0);
    const g = obj.cracks;
    g.clear();
    const shade = Math.round(255 * (0.55 + 0.45 * (pct / 100)));   // de plus en plus sombre
    obj.img.setTint(shade * 0x010101);
    if (pct <= 0 || pct >= 100) return;
    let seed = (obj.pid * 7919 + 1) | 0;          // mêmes fissures pour un même meuble
    const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
    g.lineStyle(2, 0x0b0806, 0.85);
    const n = Math.ceil((100 - pct) / 20);
    for (let i = 0; i < n; i++) {
      g.beginPath();
      let [px, py] = randomPointIn(obj.parts, rnd);  // départ toujours DANS la forme (rond, L, piano...)
      g.moveTo(px, py);
      for (let k = 0; k < 3; k++) {
        const [tx, ty] = randomPointIn(obj.parts, rnd);
        px += (tx - px) * 0.45;                    // segments brisés qui restent dans la forme (convexe)
        py += (ty - py) * 0.45;
        g.lineTo(px, py);
      }
      g.strokePath();
    }
  }

  clearBlood() {
    this.blood?.clear();
    this.shotSplats = 0;
  }

  // ------------------------------------------------------------ boucle
  update(time) {
    const cam = this.cameras.main;
    const sw = this.scale.width;
    const sh = this.scale.height;
    this.dark.setPosition(sw / 2, sh / 2);

    if (!net.ready) {
      // Accueil : on montre la carte entière, sans éclairage.
      this.dark.setVisible(false);
      this.pg.clear();
      this.fxg.clear();
      this.hud.root.hidden = true;
      cam.setZoom(Math.min(sw / net.world.w, sh / net.world.h));
      cam.centerOn(net.world.w / 2, net.world.h / 2);
      return;
    }
    if (this.built !== net.session) this.build();

    const rt = performance.now() - INTERP_DELAY;
    const meEntry = net.players.get(net.id);
    const me = meEntry?.tr.sample(rt, true);
    if (!me) return;

    const zoom = clamp(Math.min(sw / 1300, sh / 800), 0.5, 2);
    cam.setZoom(zoom);
    cam.centerOn(me.x, me.y);
    sound.setListener(me.x, me.y);
    this.dark.setVisible(true);
    const D = 3 * Math.max(sw, sh);
    this.dark.setScale(D / 1024 / zoom);

    if (net.meta.ph !== this.lastPhase) {
      if (net.meta.ph === 'play') this.clearBlood();   // nouvelle manche : on nettoie
      this.lastPhase = net.meta.ph;
    }

    for (const [id, obj] of this.propObjs) {
      const pct = net.propHp.get(id) ?? 100;
      if (pct !== obj.pct) this.setPropDamage(obj, pct);
      if (pct <= 0) continue;
      const s = net.props.get(id)?.sample(rt, false);
      if (s) obj.setPosition(s.x, s.y).setRotation(s.a);
    }

    this.drawPlayers(rt);
    this.drawFx();
    this.handleInput(time, cam, me, sw, sh);
    if (time - this.lastHud > 100) {
      this.lastHud = time;
      this.updateHud(meEntry);
      this.updateMinimap(rt);
    }
  }

  drawPlayers(rt) {
    const g = this.pg;
    const R = net.cfg.player_r;
    g.clear();
    const seen = new Set();
    const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 250);
    for (const [id, kind, x, y] of net.pickups) {        // armes au sol : halo qui pulse + silhouette + nom
      g.fillStyle(0xffd27a, 0.14 + 0.14 * pulse);
      g.fillCircle(x, y, 26);
      g.lineStyle(2, 0xd8cdb4, 0.9);                       // liseré clair : lisible sur fond sombre
      if (kind === 'shotgun') {
        g.fillStyle(0x6a4a2e, 1);
        g.fillRect(x - 22, y - 4, 16, 8);
        g.strokeRect(x - 22, y - 4, 40, 8);
        g.fillStyle(0x222222, 1);
        g.fillRect(x - 6, y - 3, 24, 6);
      } else {
        g.fillStyle(0x2a2a2e, 1);
        g.fillRect(x - 15, y - 6, 30, 11);
        g.fillRect(x - 3, y + 4, 7, 11);                  // chargeur
        g.strokeRect(x - 15, y - 6, 30, 11);
      }
      this.label(`w${id}`, WEAPON_LABEL[kind] ?? kind, x, y - 22, '#ffd27a', seen);
    }
    for (const [id, e] of net.players) {
      const s = e.tr.sample(rt, true);
      if (!s) continue;
      const zombie = e.role !== HUMAN;
      const ax = Math.cos(s.a);
      const ay = Math.sin(s.a);
      const col = zombie ? ZOMBIE_BODY : Phaser.Display.Color.HSLToColor((id * 0.137) % 1, 0.35, 0.78).color;

      if (e.flags & 4) {                                 // abattu : réapparaît bientôt (intouchable)
        g.fillStyle(ZOMBIE_BODY, 0.22);
        g.fillCircle(s.x, s.y, R);
        g.lineStyle(2, 0x7a1018, 0.5);
        g.strokeCircle(s.x, s.y, R + 6);
        this.label(`p${id}`, net.name(id), s.x, s.y - R - 12, '#6f7d63', seen);
        continue;
      }

      g.fillStyle(0x000000, 0.35);
      g.fillCircle(s.x + 3, s.y + 4, R);
      g.fillStyle(col, 1);
      g.fillCircle(s.x, s.y, R);
      g.lineStyle(3, zombie ? 0x2c4a1f : 0x4d4030, 1);
      g.strokeCircle(s.x, s.y, R);

      if (zombie) {
        g.fillStyle(0x5f8a45, 1);                       // bras tendus
        for (const side of [-1, 1]) g.fillCircle(s.x + ax * 22 - ay * side * 11, s.y + ay * 22 + ax * side * 11, 6);
        g.fillStyle(0x7a1018, 0.9);                     // bouche ensanglantée
        g.fillCircle(s.x + ax * 7, s.y + ay * 7, 5);
      } else {
        const len = id === net.id ? GUN_LENGTH[net.meta.me[2]] ?? 30 : 30;
        g.lineStyle(id === net.id && net.meta.me[2] !== 'pistol' ? 6 : 5, 0x1c1c1c, 1);   // arme
        g.lineBetween(s.x + ax * 8, s.y + ay * 8, s.x + ax * len, s.y + ay * len);
      }
      const hint = net.meta.me[3];
      if (id === net.id && zombie && hint != null && !(e.flags & 2)) {
        // Flèche discrète vers l'humain le plus proche (par les couloirs) : un petit triangle translucide.
        const hx = Math.cos(hint);
        const hy = Math.sin(hint);
        const d = R + 26;
        const tipX = s.x + hx * (d + 12);
        const tipY = s.y + hy * (d + 12);
        g.fillStyle(0xe8e0d0, 0.3);
        g.fillTriangle(tipX, tipY, s.x + hx * d - hy * 7, s.y + hy * d + hx * 7, s.x + hx * d + hy * 7, s.y + hy * d - hx * 7);
      }

      if (e.flags & 1) {                                 // ralenti
        g.lineStyle(3, 0xff9f1c, 0.9);
        g.strokeCircle(s.x, s.y, R + 5);
      }
      if (e.flags & 2) {                                 // figé
        g.fillStyle(0x000000, 0.4);
        g.fillCircle(s.x, s.y, R);
      }
      if (id === net.id) {
        g.lineStyle(2, 0xffffff, 0.9);
        g.strokeCircle(s.x, s.y, R + 4);
      }
      if (zombie && e.hp < 100) {                        // barre de vie d'un zombie blessé
        const bw = 2 * R + 8;
        g.fillStyle(0x000000, 0.7);
        g.fillRect(s.x - bw / 2 - 1, s.y + R + 5, bw + 2, 6);
        g.fillStyle(e.hp > 35 ? 0x9bc46a : 0xd23a3a, 1);
        g.fillRect(s.x - bw / 2, s.y + R + 6, bw * e.hp / 100, 4);
      }
      this.label(`p${id}`, net.name(id), s.x, s.y - R - 12, zombie ? '#a9d98a' : '#efe6d0', seen);
    }
    for (const [key, t] of this.labels) {
      if (!seen.has(key)) { t.destroy(); this.labels.delete(key); }
    }
  }

  label(key, text, x, y, color, seen) {
    seen.add(key);
    let t = this.labels.get(key);
    if (!t) {
      t = this.add.text(0, 0, text, {
        fontFamily: '"Segoe UI", system-ui, sans-serif', fontSize: '14px', fontStyle: 'bold',
        color, stroke: '#000000', strokeThickness: 3,
      }).setOrigin(0.5).setDepth(7).setResolution(2);
      this.labels.set(key, t);
    }
    if (t.text !== text) t.setText(text);
    t.setColor(color).setPosition(x, y);
  }

  drawFx() {
    const g = this.fxg;
    const now = performance.now();
    g.clear();
    this.fx = this.fx.filter((f) => f.until > now);
    for (const f of this.fx) {
      const life = (f.until - now) / (f.k === 'tracer' ? 90 : 150);
      if (f.k === 'tracer') {
        g.lineStyle(2, 0xfff1a8, life);
        g.lineBetween(f.ev.x1, f.ev.y1, f.ev.x2, f.ev.y2);
        if (f.ev.h) {
          g.fillStyle(0xffd27a, life);
          g.fillCircle(f.ev.x2, f.ev.y2, 5);
        }
      } else {
        g.fillStyle(0xffffff, 0.25 * life);
        g.slice(f.ev.x, f.ev.y, 40, f.ev.a - 0.9, f.ev.a + 0.9, false);
        g.fillPath();
      }
    }
  }

  // ------------------------------------------------------------ saisie
  handleInput(time, cam, me, sw, sh) {
    const ptr = this.input.activePointer;
    const wp = cam.getWorldPoint(ptr.x, ptr.y);
    const aim = Math.atan2(wp.y - me.y, wp.x - me.x);

    if (this.firing && time - this.lastFire > 60) {           // le serveur impose la cadence de l'arme
      this.lastFire = time;
      net.sendAct('shoot');
    }
    if (time - this.lastSend < 33) return;
    this.lastSend = time;

    const k = this.keys;
    const dx = (k.RIGHT.isDown || k.D.isDown ? 1 : 0) - (k.LEFT.isDown || k.Q.isDown || k.A.isDown ? 1 : 0);
    const dy = (k.DOWN.isDown || k.S.isDown ? 1 : 0) - (k.UP.isDown || k.Z.isDown || k.W.isDown ? 1 : 0);
    const m = Math.hypot(dx, dy) || 1;
    net.sendInput(dx / m, dy / m, aim);
  }

  // ------------------------------------------------------------ interface
  updateMinimap(rt) {
    const players = new Map();
    for (const [id, e] of net.players) players.set(id, { role: e.role, flags: e.flags, pos: e.tr.sample(rt, true) });
    this.minimap.draw(minimapDots(players, net.id));
  }

  ammoText([ammo, reloading, weapon]) {
    const name = WEAPON_LABEL[weapon] ?? weapon;
    if (reloading) return `${name} · RECHARGEMENT`;
    if (weapon === 'mp9') return `${name} ${ammo}/30`;
    const mag = weapon === 'shotgun' ? 5 : 6;
    return `${name} ${'●'.repeat(ammo)}${'○'.repeat(Math.max(0, mag - ammo))}`;
  }

  updateHud(meEntry) {
    const h = this.hud;
    const { ph, w, n, me } = net.meta;
    h.root.hidden = false;
    h.humans.textContent = n[0];
    h.zombies.textContent = n[1];

    const left = net.timeLeft();
    const mm = Math.floor(left / 60);
    const ss = String(Math.floor(left % 60)).padStart(2, '0');
    h.timer.textContent = ph === 'play' ? `${mm}:${ss}` : '--:--';
    h.timer.classList.toggle('urgent', ph === 'play' && left < 30);

    const zombie = meEntry?.role !== HUMAN;
    h.role.textContent = zombie ? 'ZOMBIE' : 'HUMAIN';
    h.role.className = zombie ? 'zombie' : 'human';
    h.ammo.textContent = zombie ? '' : this.ammoText(me);

    let text = '';
    let cls = '';
    if (ph === 'wait') {
      text = `En attente de joueurs (${net.players.size}/${net.cfg.min})`;
    } else if (ph === 'intermission') {
      text = `Manche dans ${Math.ceil(net.timeLeft())}`;
    } else if (ph === 'play' && net.freezeLeft() > 0) {
      const s = Math.ceil(net.freezeLeft());
      text = zombie ? `Vous êtes le patient zéro. Réveil dans ${s}` : `Un zombie se réveille dans ${s}. Barricadez-vous !`;
    } else if (ph === 'end') {
      if (w === 'humans') { text = 'Les humains ont survécu'; cls = 'win-humans'; }
      else if (w === 'zombies') { text = 'Plus aucun humain'; cls = 'win-zombies'; }
      else text = 'Manche annulée : pas assez de joueurs';
    }
    h.banner.textContent = text;
    h.banner.className = cls;
  }
}
