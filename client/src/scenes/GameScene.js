import Phaser from 'phaser';
import { sound } from '../audio.js';
import { INTERP_DELAY, net } from '../net.js';

// Couleurs « dessus de meuble » : [flanc, plateau]
const PROP_STYLE = {
  chair: [0x6b4f36, 0x8a6a4a],
  crate: [0x7d6030, 0x9c7a3c],
  table: [0x55402b, 0x75573a],
  sofa: [0x5e2b2b, 0x7a3b3b],
  bed: [0x39475f, 0x52668a],
  wardrobe: [0x2a1f19, 0x44342b],
};
const ROOM_TINTS = [0x15120f, 0x12150f, 0x161214, 0x11131a, 0x171410, 0x131315];
const HUMAN = 0;
const ZOMBIE_BODY = 0x7ea35c;
const BLOODS = [0x6e0f16, 0x8b1a22, 0x540b10];
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
    this.lastPhase = null;
    this.lastSend = 0;
    this.lastFire = 0;
    this.lastHud = 0;
    this.firing = false;

    this.cameras.main.setBackgroundColor('#030403');
    this.floor = this.add.graphics().setDepth(0);
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
    const f = this.floor;
    f.clear();
    ROOM_TINTS.forEach((c, i) => {
      f.fillStyle(c, 1);
      f.fillRect((i % 3) * (w / 3), Math.floor(i / 3) * (h / 2), w / 3, h / 2);
    });
    f.lineStyle(1, 0x000000, 0.35);          // lattes de parquet / carrelage
    for (let x = 0; x <= w; x += 80) f.lineBetween(x, 0, x, h);
    for (let y = 0; y <= h; y += 80) f.lineBetween(0, y, w, y);
    for (const [cx, cy, ww, hh] of net.walls) {
      f.fillStyle(0x4a4742, 1);
      f.fillRect(cx - ww / 2, cy - hh / 2, ww, hh);
      f.lineStyle(3, 0x1a1917, 1);
      f.strokeRect(cx - ww / 2, cy - hh / 2, ww, hh);
    }

    for (const [id, info] of net.propInfo) {
      const [side, top] = PROP_STYLE[info.kind];
      const c = this.add.container(0, 0).setDepth(2);
      const base = this.add.rectangle(0, 0, info.w, info.h, side).setStrokeStyle(2, 0x000000, 0.7);
      const plate = this.add.rectangle(0, 0, info.w - 8, info.h - 8, top);
      c.add([base, plate]);
      if (info.kind === 'bed') c.add(this.add.rectangle(0, -info.h / 2 + 18, info.w - 20, 24, 0xcfc8b8));
      if (info.kind === 'sofa') c.add(this.add.rectangle(0, -info.h / 2 + 9, info.w - 8, 14, side));
      if (info.kind === 'wardrobe') c.add(this.add.rectangle(0, 0, 3, info.h - 8, 0x000000, 0.6));
      this.propObjs.set(id, c);
    }
  }

  // ------------------------------------------------------------ événements
  onNetEvent(ev) {
    const now = performance.now();
    if (ev.k === 'shot') {
      sound.shot(ev.x1, ev.y1);
      this.addFx({ k: 'tracer', ev, until: now + 90 });
      if (ev.h === 'zombie' && this.shotSplats < MAX_SHOT_SPLATS) {
        this.shotSplats += 1;
        this.splat(ev.x2, ev.y2, 4, 10);
      }
    } else if (ev.k === 'hit') {
      sound.hit(ev.x, ev.y, ev.n > 0);
      this.addFx({ k: 'swing', ev, until: now + 150 });
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
      const s = net.props.get(id)?.sample(rt, false);
      if (s) obj.setPosition(s.x, s.y).setRotation(s.a);
    }

    this.drawPlayers(rt);
    this.drawFx();
    this.handleInput(time, cam, me, sw, sh);
    if (time - this.lastHud > 100) {
      this.lastHud = time;
      this.updateHud(meEntry);
    }
  }

  drawPlayers(rt) {
    const g = this.pg;
    const R = net.cfg.player_r;
    g.clear();
    const seen = new Set();
    for (const [id, e] of net.players) {
      const s = e.tr.sample(rt, true);
      if (!s) continue;
      const zombie = e.role !== HUMAN;
      const ax = Math.cos(s.a);
      const ay = Math.sin(s.a);
      const col = zombie ? ZOMBIE_BODY : Phaser.Display.Color.HSLToColor((id * 0.137) % 1, 0.35, 0.78).color;

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
        g.lineStyle(5, 0x1c1c1c, 1);                    // pistolet
        g.lineBetween(s.x + ax * 8, s.y + ay * 8, s.x + ax * 30, s.y + ay * 30);
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

    if (this.firing && time - this.lastFire > 120) {
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
    h.ammo.textContent = zombie ? '' : (me[1] ? 'RECHARGEMENT' : '●'.repeat(me[0]) + '○'.repeat(Math.max(0, 6 - me[0])));

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
