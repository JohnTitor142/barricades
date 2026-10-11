import assert from 'node:assert/strict';
import test from 'node:test';
import { minimapDots } from '../src/minimap.js';

const at = (x, y, a = 0) => ({ x, y, a });
const world = () => new Map([
  [1, { role: 0, flags: 0, pos: at(100, 100, 1.5) }],   // moi (selon les cas)
  [2, { role: 0, flags: 0, pos: at(200, 200) }],        // autre humain
  [3, { role: 1, flags: 0, pos: at(300, 300) }],        // zombie
  [4, { role: 1, flags: 4, pos: at(400, 400) }],        // zombie en réapparition
]);

test('un humain ne voit que lui-même (pas de triche sur la position des autres)', () => {
  const dots = minimapDots(world(), 1);
  assert.deepEqual(dots, [{ x: 100, y: 100, a: 1.5, kind: 'me-human' }]);
});

test('un zombie voit tous les zombies alliés, les abattus en plus pâle, et pas les humains', () => {
  const w = world();
  w.get(1).role = 1;
  const dots = minimapDots(w, 1);
  assert.deepEqual(dots.map((d) => d.kind), ['ally', 'ally-down', 'me-zombie']);
  assert.ok(!dots.some((d) => d.x === 200));
  assert.equal(dots.at(-1).kind, 'me-zombie');          // soi dessiné en dernier, par-dessus
});

test('sans position connue (pas encore de snapshot), rien à afficher', () => {
  assert.deepEqual(minimapDots(new Map(), 1), []);
  assert.deepEqual(minimapDots(new Map([[1, { role: 0, flags: 0, pos: null }]]), 1), []);
});
