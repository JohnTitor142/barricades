import assert from 'node:assert/strict';
import test from 'node:test';
import { HEAR_DIST, sound, spatial } from '../src/audio.js';

test('un bruit sur soi est à plein volume et centré', () => {
  assert.deepEqual(spatial(0, 0), { gain: 1, pan: 0 });
});

test('le volume baisse avec la distance et coupe au-delà de la portée', () => {
  const near = spatial(200, 0).gain;
  const far = spatial(800, 0).gain;
  assert.ok(near > far && far > 0);
  assert.equal(spatial(HEAR_DIST, 0), null);
  assert.equal(spatial(0, HEAR_DIST + 50), null);
});

test('gauche / droite selon la position, borné à ±1', () => {
  assert.ok(spatial(-300, 0).pan < 0);
  assert.ok(spatial(300, 0).pan > 0);
  assert.equal(spatial(1000, 0).pan, 1);
  assert.equal(spatial(0, 500).pan, 0);
});

test('sans AudioContext débloqué, les effets ne plantent pas', () => {
  sound.shot(0, 0);
  sound.hit(0, 0, true);
  sound.setMusic(false);
  assert.equal(sound.musicOn, false);
});
