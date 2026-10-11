// Connexion WebSocket + état interpolé.
// Le serveur envoie ~30 snapshots/s. On affiche le monde avec 100 ms de retard
// et on interpole entre deux états connus : le mouvement reste fluide malgré la gigue réseau.
// Pour les meubles, le serveur n'envoie que ceux qui bougent : une « piste » (Track) par entité
// garde un court historique, et un meuble immobile reste simplement à sa dernière position.

export const INTERP_DELAY = 100; // ms
const TELEPORT = 250;            // au-delà, pas de lissage (réapparition, changement de manche)

export function lerpAngle(a, b, k) {
  const d = ((((b - a + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI)) - Math.PI;
  return a + d * k;
}

export class Track {
  constructor() {
    this.h = [];
  }

  push(t, x, y, a) {
    const h = this.h;
    const l = h[h.length - 1];
    if (l && l.x === x && l.y === y && l.a === a) return;
    h.push({ t, x, y, a });
    if (h.length > 8) h.shift();
  }

  /** Position à l'instant rt (ms). `wrap` : l'angle est modulo 2π (joueurs), sinon continu (meubles). */
  sample(rt, wrap) {
    const h = this.h;
    const n = h.length;
    if (!n) return null;
    if (rt >= h[n - 1].t) return h[n - 1];
    if (rt <= h[0].t) return h[0];
    for (let i = n - 1; i > 0; i--) {
      const a = h[i - 1];
      if (a.t <= rt) {
        const b = h[i];
        if (Math.hypot(b.x - a.x, b.y - a.y) > TELEPORT) return b;
        const k = (rt - a.t) / (b.t - a.t);
        return {
          x: a.x + (b.x - a.x) * k,
          y: a.y + (b.y - a.y) * k,
          a: wrap ? lerpAngle(a.a, b.a, k) : a.a + (b.a - a.a) * k,
        };
      }
    }
    return h[n - 1];
  }
}

export class Net {
  constructor() {
    this.listeners = [];
    this.onClose = () => {};
    this.session = 0;
    this._reset();
  }

  _reset() {
    this.ws = null;
    this.id = null;
    this.ready = false;
    this.world = { w: 2400, h: 1600 };
    this.walls = [];
    this.rooms = [];
    this.propInfo = new Map(); // id -> {kind, w, h}
    this.props = new Map();    // id -> Track
    this.propHp = new Map();   // id -> PV en % (0 = cassé)
    this.players = new Map();  // id -> {tr, role, flags, hp}
    this.names = new Map();
    this.cfg = { round: 300, freeze: 10, min: 2, player_r: 16 };
    this.meta = { ph: 'wait', tl: 0, w: null, fz: 0, n: [0, 0], me: [0, 0], at: 0 };
  }

  on(fn) {
    this.listeners.push(fn);
  }

  connect(name) {
    return new Promise((resolve, reject) => {
      this._reset();
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${location.host}/ws`);
      this.ws = ws;
      ws.onopen = () => ws.send(JSON.stringify({ t: 'join', name }));
      ws.onerror = () => reject(new Error('Serveur injoignable.'));
      ws.onclose = (e) => {
        const wasReady = this.ready;
        this.ready = false;
        if (wasReady) this.onClose(e.code);
        else reject(new Error(e.code === 1013 ? 'Salon complet (24 joueurs).' : 'Connexion refusée.'));
      };
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.t === 'welcome') {
          this._welcome(m);
          resolve();
        } else if (m.t === 's') {
          this._onState(m);
        }
      };
    });
  }

  _welcome(m) {
    const t = performance.now() - 1000;
    this.id = m.id;
    this.world = { w: m.w, h: m.h };
    this.walls = m.walls;
    this.rooms = m.rooms ?? [];
    this.cfg = m.cfg;
    for (const [id, kind, w, h] of m.props) {
      this.propInfo.set(id, { kind, w, h });
      this.props.set(id, new Track());
    }
    for (const [id, x, y, a] of m.pos) this.props.get(id)?.push(t, x, y, a);
    for (const [id, pct] of m.ps ?? []) this.propHp.set(id, pct);
    this._setNames(m.names);
    this.session += 1;
    this.ready = true;
  }

  _setNames(obj) {
    this.names = new Map(Object.entries(obj).map(([k, v]) => [Number(k), v]));
  }

  _onState(m) {
    const t = performance.now();
    this.meta = { ph: m.ph, tl: m.tl, w: m.w, fz: m.fz, n: m.n, me: m.me ?? [0, 0], at: t };
    if (m.names) this._setNames(m.names);

    const seen = new Set();
    for (const [id, x, y, a, role, flags, hp = 100] of m.p) {
      seen.add(id);
      let e = this.players.get(id);
      if (!e) { e = { tr: new Track(), role, flags, hp }; this.players.set(id, e); }
      e.role = role;
      e.flags = flags;
      e.hp = hp;
      e.tr.push(t, x, y, a);
    }
    for (const id of this.players.keys()) if (!seen.has(id)) this.players.delete(id);

    for (const list of [m.pr, m.pf]) {
      if (!list) continue;
      for (const [id, x, y, a] of list) this.props.get(id)?.push(t, x, y, a);
    }
    for (const [id, pct] of m.ps ?? []) this.propHp.set(id, pct);
    for (const ev of m.ev) for (const fn of this.listeners) fn(ev);
  }

  /** Secondes restantes de la phase courante, lissées entre deux snapshots. */
  timeLeft() {
    return Math.max(0, this.meta.tl - (performance.now() - this.meta.at) / 1000);
  }

  freezeLeft() {
    return Math.max(0, this.meta.fz - (performance.now() - this.meta.at) / 1000);
  }

  name(id) {
    return this.names.get(id) ?? '???';
  }

  sendInput(dx, dy, a) {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({
      t: 'input',
      dx: Math.round(dx * 100) / 100,
      dy: Math.round(dy * 100) / 100,
      a: Math.round(a * 100) / 100,
    }));
  }

  sendAct(kind) {
    if (this.ready && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(`{"t":"act","k":"${kind}"}`);
    }
  }
}

export const net = new Net();
