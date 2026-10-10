import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lerpAngle, Track } from '../src/net.js';

test('interpole linéairement entre deux états', () => {
  const t = new Track();
  t.push(0, 0, 0, 0);
  t.push(100, 100, 50, 1);
  const s = t.sample(50, false);
  assert.equal(s.x, 50);
  assert.equal(s.y, 25);
  assert.equal(s.a, 0.5);
});

test("un meuble qui ne bouge plus reste à sa dernière position", () => {
  const t = new Track();
  t.push(0, 0, 0, 0);
  t.push(100, 10, 0, 0);
  assert.equal(t.sample(5000, false).x, 10);
});

test('pas de lissage sur une téléportation', () => {
  const t = new Track();
  t.push(0, 0, 0, 0);
  t.push(100, 1000, 1000, 0);
  assert.equal(t.sample(50, true).x, 1000);
});

test("l'angle prend le chemin le plus court (passage de ±π)", () => {
  const a = lerpAngle(3.0, -3.0, 0.5);
  assert.ok(Math.abs(Math.abs(a) - Math.PI) < 0.2, `a=${a}`);
});

test('états identiques consécutifs ne gonflent pas l\'historique', () => {
  const t = new Track();
  for (let i = 0; i < 20; i++) t.push(i * 33, 5, 5, 0);
  assert.equal(t.h.length, 1);
});
