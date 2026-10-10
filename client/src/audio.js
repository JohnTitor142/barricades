// Sons du jeu, entièrement synthétisés avec la Web Audio API (aucun fichier à charger).
// Le navigateur interdit de jouer du son avant une action de l'utilisateur : on crée donc
// l'AudioContext au premier clic (« Entrer dans le salon ») via unlock().

export const HEAR_DIST = 1100; // au-delà (en pixels du monde), un bruit n'est plus audible

/** Volume (0..1) et panoramique (-1 gauche .. 1 droite) d'un bruit vu depuis l'auditeur. */
export function spatial(dx, dy, maxDist = HEAR_DIST) {
  const d = Math.hypot(dx, dy);
  if (d >= maxDist) return null;
  const k = 1 - d / maxDist;
  return { gain: k * k, pan: Math.max(-1, Math.min(1, dx / 600)) };
}

const STORE_KEY = 'barricade:music';
// La mineur, Fa, Ré mineur, Mi : progression sombre, une note tenue par accord.
const CHORDS = [[220, 261.6, 329.6], [174.6, 220, 261.6], [146.8, 174.6, 220], [164.8, 207.7, 246.9]];
const CHORD_LEN = 8;    // secondes par accord
const BEAT_EVERY = 1.5; // secondes entre deux battements de cœur
const MAX_VOICES = 16;  // effets sonores simultanés au maximum (une fusillade ne sature pas)
const VOICE_LIFE = 600; // ms : durée max d'un effet, après quoi on le débranche

class Sound {
  constructor() {
    this.ctx = null;
    this.musicOn = true;
    try { this.musicOn = globalThis.localStorage?.getItem(STORE_KEY) !== 'off'; } catch { /* stockage bloqué */ }
    this.listener = { x: 0, y: 0 };
    this.voices = 0;
    this.onMusicChange = () => {};
  }

  unlock() {
    if (!this.ctx) {
      const AC = globalThis.AudioContext ?? globalThis.webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.8;
      this.master.connect(this.ctx.destination);
      this.sfxBus = this.ctx.createGain();
      this.sfxBus.connect(this.master);
      this.musicBus = this.ctx.createGain();
      this.musicBus.gain.value = 0;
      this.musicBus.connect(this.master);
      this.noise = this.makeNoise();
    }
    this.ctx.resume();
    if (this.musicOn) this.startMusic();
  }

  makeNoise() {
    const buf = this.ctx.createBuffer(1, this.ctx.sampleRate, this.ctx.sampleRate);
    const data = buf.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    return buf;
  }

  setListener(x, y) {
    this.listener.x = x;
    this.listener.y = y;
  }

  // ------------------------------------------------------------ musique
  toggleMusic() {
    this.setMusic(!this.musicOn);
  }

  setMusic(on) {
    this.musicOn = on;
    try { localStorage.setItem(STORE_KEY, on ? 'on' : 'off'); } catch { /* stockage bloqué */ }
    this.onMusicChange(on);
    if (!this.ctx) return;
    if (on) this.startMusic();
    else this.stopMusic();
  }

  startMusic() {
    if (this.music) return;
    const ctx = this.ctx;
    const t = ctx.currentTime;
    this.musicBus.gain.cancelScheduledValues(t);
    this.musicBus.gain.setTargetAtTime(0.22, t, 1.2);

    // Bourdon grave : deux dents de scie légèrement désaccordées, filtre qui « respire ».
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 180;
    lp.Q.value = 6;
    lp.connect(this.musicBus);
    const lfo = ctx.createOscillator();
    const lfoAmt = ctx.createGain();
    lfo.frequency.value = 0.06;
    lfoAmt.gain.value = 90;
    lfo.connect(lfoAmt).connect(lp.frequency);
    const drones = [55, 55.4, 27.5].map((f) => {
      const o = ctx.createOscillator();
      o.type = 'sawtooth';
      o.frequency.value = f;
      o.connect(lp);
      return o;
    });
    for (const o of [lfo, ...drones]) o.start(t);

    this.music = { nodes: [lfo, ...drones], nextChord: t + 0.5, nextBeat: t + 1, chord: 0 };
    this.schedule();
    this.timer = setInterval(() => this.schedule(), 250);
  }

  stopMusic() {
    if (!this.music) return;
    const t = this.ctx.currentTime;
    this.musicBus.gain.cancelScheduledValues(t);
    this.musicBus.gain.setTargetAtTime(0, t, 0.3);
    for (const o of this.music.nodes) o.stop(t + 1.5);
    clearInterval(this.timer);
    this.music = null;
  }

  // Programme les notes un peu à l'avance : les minuteries JS sont imprécises,
  // l'horloge audio (ctx.currentTime) ne l'est pas.
  schedule() {
    const m = this.music;
    const horizon = this.ctx.currentTime + 1.5;
    while (m.nextChord < horizon) {
      for (const f of CHORDS[m.chord % CHORDS.length]) this.padNote(f, m.nextChord, CHORD_LEN);
      m.chord += 1;
      m.nextChord += CHORD_LEN;
    }
    while (m.nextBeat < horizon) {
      this.thump(m.nextBeat, 0.5);
      this.thump(m.nextBeat + 0.22, 0.35);
      m.nextBeat += BEAT_EVERY;
    }
  }

  padNote(freq, t, len) {
    const ctx = this.ctx;
    const o = ctx.createOscillator();
    const lp = ctx.createBiquadFilter();
    const g = ctx.createGain();
    o.type = 'triangle';
    o.frequency.value = freq / 2;
    o.detune.value = (Math.random() - 0.5) * 12;
    lp.type = 'lowpass';
    lp.frequency.value = 600;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(0.07, t + len * 0.4);
    g.gain.linearRampToValueAtTime(0, t + len * 1.05);
    o.connect(lp).connect(g).connect(this.musicBus);
    o.start(t);
    o.stop(t + len * 1.1);
  }

  thump(t, vol) {
    const ctx = this.ctx;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.setValueAtTime(70, t);
    o.frequency.exponentialRampToValueAtTime(38, t + 0.15);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
    o.connect(g).connect(this.musicBus);
    o.start(t);
    o.stop(t + 0.22);
  }

  // ------------------------------------------------------------ effets
  /** Sortie d'un effet placé dans le monde, ou null s'il est trop loin pour être entendu. */
  out(x, y, vol) {
    if (!this.ctx || this.ctx.state !== 'running' || this.voices >= MAX_VOICES) return null;
    const s = spatial(x - this.listener.x, y - this.listener.y);
    if (!s) return null;
    const g = this.ctx.createGain();
    this.voices += 1;
    setTimeout(() => { g.disconnect(); this.voices -= 1; }, VOICE_LIFE);
    g.gain.value = vol * s.gain;
    if (this.ctx.createStereoPanner) {
      const p = this.ctx.createStereoPanner();
      p.pan.value = s.pan;
      g.connect(p).connect(this.sfxBus);
    } else {
      g.connect(this.sfxBus);
    }
    return g;
  }

  noiseBurst(dest, t, len, type, freq, vol, rate = 1) {
    const src = this.ctx.createBufferSource();
    const f = this.ctx.createBiquadFilter();
    const g = this.ctx.createGain();
    src.buffer = this.noise;
    src.playbackRate.value = rate;
    f.type = type;
    f.frequency.value = freq;
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + len);
    src.connect(f).connect(g).connect(dest);
    src.start(t, Math.random() * 0.5);
    src.stop(t + len + 0.02);
    return f;
  }

  boom(dest, t, f0, f1, len, vol, type = 'sine') {
    const o = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(f1, t + len);
    g.gain.setValueAtTime(vol, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + len);
    o.connect(g).connect(dest);
    o.start(t);
    o.stop(t + len + 0.02);
  }

  /** Coup de pistolet tiré depuis (x, y). */
  shot(x, y) {
    const dest = this.out(x, y, 0.9);
    if (!dest) return;
    const t = this.ctx.currentTime;
    const r = 0.9 + Math.random() * 0.2; // légère variation pour éviter l'effet « disque rayé »
    this.noiseBurst(dest, t, 0.03, 'highpass', 2500, 0.9, r);   // claquement
    this.noiseBurst(dest, t, 0.22, 'lowpass', 1400 * r, 0.8, r); // détonation
    this.boom(dest, t, 160 * r, 45, 0.16, 0.9);                  // souffle grave
  }

  /** Coup porté en (x, y) ; impact = un meuble ou un joueur a été touché. */
  hit(x, y, impact) {
    const dest = this.out(x, y, 0.7);
    if (!dest) return;
    const t = this.ctx.currentTime;
    const sweep = this.noiseBurst(dest, t, 0.14, 'bandpass', 500, 0.35);
    sweep.Q.value = 2;
    sweep.frequency.exponentialRampToValueAtTime(1800, t + 0.12);
    if (impact) {
      const ti = t + 0.05;
      this.boom(dest, ti, 130, 50, 0.2, 0.9);
      this.boom(dest, ti, 240 + Math.random() * 60, 160, 0.06, 0.35, 'triangle'); // « toc » du bois
      this.noiseBurst(dest, ti, 0.05, 'lowpass', 900, 0.5);
    }
  }
}

export const sound = new Sound();
