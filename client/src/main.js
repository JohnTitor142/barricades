import Phaser from 'phaser';
import './style.css';
import { sound } from './audio.js';
import { net } from './net.js';
import { GameScene } from './scenes/GameScene.js';

// Phaser plante au démarrage si la fenêtre fait 0 x 0 (onglet ouvert en arrière-plan, iframe masquée) :
// on attend d'avoir une vraie taille.
function startGame() {
  if (!window.innerWidth || !window.innerHeight) {
    window.addEventListener('resize', startGame, { once: true });
    return;
  }
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent: 'game',
    backgroundColor: '#030403',
    scale: { mode: Phaser.Scale.RESIZE, width: window.innerWidth, height: window.innerHeight },
    scene: [GameScene],
  });
  if (import.meta.env.DEV) window.__barricade = { game, net, sound }; // inspection depuis la console (F12)
}
startGame();

const $ = (id) => document.getElementById(id);
const menu = $('menu');
const playBtn = $('play');
const nameInput = $('name');
const errorEl = $('error');

nameInput.value = localStorage.getItem('barricade:name') ?? '';

function toast(text, kind) {
  const el = document.createElement('div');
  el.textContent = text;
  el.className = kind;
  $('feed').append(el);
  while ($('feed').children.length > 5) $('feed').firstChild.remove();
  setTimeout(() => el.remove(), 6000);
}

net.on((ev) => {
  if (ev.k === 'infect') toast(`${net.name(ev.id)} a été infecté par ${net.name(ev.by)}`, 'infect');
  else if (ev.k === 'zero') toast(`${net.name(ev.id)} est le patient zéro`, 'zero');
  else if (ev.k === 'kill') toast(`${net.name(ev.by)} a abattu ${net.name(ev.id)}`, 'kill');
});

function showMenu(message) {
  $('hud').hidden = true;
  menu.hidden = false;
  playBtn.disabled = false;
  errorEl.textContent = message ?? '';
}

const musicBtn = $('music');
sound.onMusicChange = (on) => {
  musicBtn.setAttribute('aria-pressed', String(on));
  musicBtn.classList.toggle('off', !on);
};
sound.onMusicChange(sound.musicOn);
musicBtn.addEventListener('click', () => {
  sound.toggleMusic();
  musicBtn.blur(); // sinon Espace (frapper) re-cliquerait le bouton
});
window.addEventListener('keydown', (e) => {
  if (e.code !== 'KeyM' || e.repeat || e.target instanceof HTMLInputElement) return;
  sound.toggleMusic();
});

// Après une mise à jour, le serveur redémarre : on attend qu'il réponde, puis on recharge la page
// pour récupérer le nouveau client (sinon on jouerait avec l'ancien code contre le nouveau serveur).
let reloading = false;
async function reloadWhenServerIsBack(message) {
  showMenu(message);
  if (reloading) return;
  reloading = true;
  playBtn.disabled = true;
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const r = await fetch('/health', { cache: 'no-store' });
      if (r.ok) { location.reload(); return; }
    } catch { /* pas encore revenu */ }
  }
  reloading = false;
  showMenu('Le serveur ne répond plus. Rechargez la page plus tard.');
}

net.onClose = () => reloadWhenServerIsBack('Connexion perdue (mise à jour du serveur ?) : rechargement automatique…');

$('menu-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  sound.unlock(); // le navigateur n'autorise le son qu'après un geste de l'utilisateur
  playBtn.disabled = true;
  errorEl.textContent = '';
  const name = nameInput.value.trim();
  localStorage.setItem('barricade:name', name);
  try {
    await net.connect(name);
    menu.hidden = true;
    $('hud').hidden = false;
  } catch (err) {
    if (err.message === 'VERSION') reloadWhenServerIsBack('Nouvelle version du jeu : rechargement…');
    else showMenu(err.message);
  }
});
