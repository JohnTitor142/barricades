import assert from 'node:assert/strict';
import test from 'node:test';
import { kindBounds, partBounds, randomPointIn, styleOf } from '../src/furniture.js';

const PIANO = [['box', 140, 60, 0, -45], ['poly', [[-70, -15], [70, -15], [45, 60], [-10, 80], [-55, 55]]]];
const SOFA_L = [['box', 150, 50, 0, -30], ['box', 50, 70, 50, 30]];

function inside(parts, [x, y]) {
  return parts.some((p) => {
    if (p[0] === 'box') return Math.abs(x - p[3]) <= p[1] / 2 && Math.abs(y - p[4]) <= p[2] / 2;
    if (p[0] === 'circle') return Math.hypot(x - p[2], y - p[3]) <= p[1];
    // polygone convexe : du même côté de toutes les arêtes
    const pts = p[1];
    let sign = 0;
    for (let i = 0; i < pts.length; i++) {
      const [ax, ay] = pts[i];
      const [bx, by] = pts[(i + 1) % pts.length];
      const c = Math.sign((bx - ax) * (y - ay) - (by - ay) * (x - ax));
      if (c && sign && c !== sign) return false;
      if (c) sign = c;
    }
    return true;
  });
}

test('boîtes englobantes : rectangle décalé, cercle, polygone', () => {
  assert.deepEqual(partBounds(['box', 50, 70, 50, 30]), [25, -5, 75, 65]);
  assert.deepEqual(partBounds(['circle', 22, 0, 0]), [-22, -22, 22, 22]);
  assert.deepEqual(kindBounds(PIANO), [-70, -75, 70, 80]);
  assert.deepEqual(kindBounds(SOFA_L), [-75, -55, 75, 65]);
});

test('les fissures partent toujours de l\'intérieur du meuble (piano, canapé d\'angle, tonneau)', () => {
  let seed = 42;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
  for (const parts of [PIANO, SOFA_L, [['circle', 22, 0, 0]]]) {
    for (let i = 0; i < 300; i++) assert.ok(inside(parts, randomPointIn(parts, rnd)));
  }
});

test('un type de meuble inconnu du client garde un style par défaut', () => {
  assert.equal(styleOf('nouveau_meuble').length, 2);
  assert.notDeepEqual(styleOf('piano'), styleOf('nouveau_meuble'));
});
