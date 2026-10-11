// Mini-carte translucide (canevas HTML au-dessus du jeu) : décor dessiné une fois, points rafraîchis ~10 fois/s.
// Humain : on ne voit que soi. Zombie : on voit aussi tous les autres zombies (alliés).

const HUMAN = 0;
const FLAG_RESPAWNING = 4;

/** Points à afficher. `players` : Map id -> {role, flags, pos:{x, y, a}}. Pur : testé sous Node. */
export function minimapDots(players, meId) {
  const me = players.get(meId);
  if (!me?.pos) return [];
  const dots = [];
  if (me.role !== HUMAN) {
    for (const [id, p] of players) {
      if (id === meId || p.role === HUMAN || !p.pos) continue;
      dots.push({ x: p.pos.x, y: p.pos.y, kind: p.flags & FLAG_RESPAWNING ? 'ally-down' : 'ally' });
    }
  }
  dots.push({ x: me.pos.x, y: me.pos.y, a: me.pos.a, kind: me.role === HUMAN ? 'me-human' : 'me-zombie' });
  return dots;                                    // soi en dernier : dessiné par-dessus les autres
}

const GROUND = {
  floor: '#3a3128', wood: '#4a3a2a', tile: '#3c4248', carpet: '#4a2a33', stone: '#48463f', straw: '#5c4f2a',
  concrete: '#3a3a3a', grass: '#1f2e19', asphalt: '#232326', sidewalk: '#4c4945', dirt: '#4a3826',
  field: '#36421d', gravel: '#47443d', cemetery: '#262e24',
};

export class Minimap {
  constructor(canvas, width = 220) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.width = width;
    this.bg = null;
  }

  /** Redessine le fond quand on rejoint une partie (nouvelle carte). Renvoie la hauteur en px CSS. */
  build(net) {
    const { w, h } = net.world;
    const dpr = globalThis.devicePixelRatio || 1;
    this.k = this.width / w;
    this.height = Math.round(h * this.k);
    this.canvas.style.width = `${this.width}px`;
    this.canvas.style.height = `${this.height}px`;
    this.canvas.width = Math.round(this.width * dpr);
    this.canvas.height = Math.round(this.height * dpr);
    this.dpr = dpr;

    const bg = document.createElement('canvas');
    bg.width = this.canvas.width;
    bg.height = this.canvas.height;
    const c = bg.getContext('2d');
    const s = this.k * dpr;
    c.scale(s, s);
    c.fillStyle = GROUND[net.base] ?? GROUND.floor;
    c.fillRect(0, 0, w, h);
    for (const [ground, poly] of net.areas) {
      c.fillStyle = GROUND[ground] ?? GROUND.floor;
      c.beginPath();
      poly.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y)));
      c.closePath();
      c.fill();
    }
    c.lineCap = 'round';
    c.strokeStyle = '#b8b2a6';
    for (const [x1, y1, x2, y2, t] of net.walls) {
      c.lineWidth = Math.max(t, 2 / s);           // les clôtures fines restent visibles
      c.beginPath();
      c.moveTo(x1, y1);
      c.lineTo(x2, y2);
      c.stroke();
    }
    c.fillStyle = '#6b7a62';
    for (const [, x, y, r] of net.obstacles) {
      c.beginPath();
      c.arc(x, y, r, 0, Math.PI * 2);
      c.fill();
    }
    this.bg = bg;
    return this.height;
  }

  draw(dots) {
    if (!this.bg) return;
    const c = this.ctx;
    const s = this.k * this.dpr;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, this.canvas.width, this.canvas.height);
    c.drawImage(this.bg, 0, 0);
    for (const d of dots) {
      const x = d.x * s;
      const y = d.y * s;
      if (d.kind === 'ally' || d.kind === 'ally-down') {
        c.fillStyle = d.kind === 'ally' ? '#8fd16a' : 'rgba(143, 209, 106, 0.35)';
        c.beginPath();
        c.arc(x, y, 3 * this.dpr, 0, Math.PI * 2);
        c.fill();
        continue;
      }
      const r = 4.5 * this.dpr;                   // soi : point cerclé + flèche dans la direction visée
      c.fillStyle = d.kind === 'me-zombie' ? '#c6f2a8' : '#ffffff';
      c.strokeStyle = '#000000';
      c.lineWidth = 1.5 * this.dpr;
      c.beginPath();
      c.arc(x, y, r, 0, Math.PI * 2);
      c.fill();
      c.stroke();
      c.strokeStyle = c.fillStyle;
      c.lineWidth = 2 * this.dpr;
      c.beginPath();
      c.moveTo(x, y);
      c.lineTo(x + Math.cos(d.a) * r * 2.4, y + Math.sin(d.a) * r * 2.4);
      c.stroke();
    }
  }
}
