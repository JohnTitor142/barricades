// Meubles : le serveur envoie la géométrie de chaque type (formes convexes dans le repère du meuble) ;
// ici on la dessine. Chaque type est dessiné UNE fois dans une texture, que tous les meubles réutilisent.
// Formes : ['box', w, h, dx, dy] | ['circle', r, dx, dy] | ['poly', [[x, y], ...]]

// [flanc, plateau] par type ; un type inconnu (nouveau côté serveur) reste dessiné en gris.
export const PROP_STYLE = {
  chair: [0x6b4f36, 0x8a6a4a],
  barrel: [0x4a3220, 0x6e4a2c],
  crate: [0x7d6030, 0x9c7a3c],
  table: [0x55402b, 0x75573a],
  round_table: [0x5a412a, 0x7c5a3b],
  bookshelf: [0x3b2a1e, 0x52392a],
  sofa_l: [0x5e2b2b, 0x7a3b3b],
  bed: [0x39475f, 0x52668a],
  wardrobe: [0x2a1f19, 0x44342b],
  fridge: [0x9da29c, 0xc9cec6],
  piano: [0x0b0b0d, 0x1d1d22],
};
const DEFAULT_STYLE = [0x4a4a4a, 0x6a6a6a];
export const styleOf = (kind) => PROP_STYLE[kind] ?? DEFAULT_STYLE;

/** Boîte englobante [x0, y0, x1, y1] d'une forme, dans le repère du meuble. */
export function partBounds(part) {
  if (part[0] === 'box') {
    const [, w, h, dx, dy] = part;
    return [dx - w / 2, dy - h / 2, dx + w / 2, dy + h / 2];
  }
  if (part[0] === 'circle') {
    const [, r, dx, dy] = part;
    return [dx - r, dy - r, dx + r, dy + r];
  }
  const xs = part[1].map((p) => p[0]);
  const ys = part[1].map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/** Boîte englobante d'un meuble entier. */
export function kindBounds(parts) {
  const b = [Infinity, Infinity, -Infinity, -Infinity];
  for (const p of parts) {
    const [x0, y0, x1, y1] = partBounds(p);
    b[0] = Math.min(b[0], x0); b[1] = Math.min(b[1], y0);
    b[2] = Math.max(b[2], x1); b[3] = Math.max(b[3], y1);
  }
  return b;
}

/** Point tiré à l'intérieur du meuble (fissures). `rnd` : générateur dans [0, 1[ (graine fixe par meuble). */
export function randomPointIn(parts, rnd) {
  const part = parts[Math.floor(rnd() * parts.length) % parts.length];
  if (part[0] === 'box') {
    const [, w, h, dx, dy] = part;
    return [dx + (rnd() - 0.5) * w * 0.8, dy + (rnd() - 0.5) * h * 0.8];
  }
  if (part[0] === 'circle') {
    const [, r, dx, dy] = part;
    const a = rnd() * Math.PI * 2;
    const d = Math.sqrt(rnd()) * r * 0.8;
    return [dx + Math.cos(a) * d, dy + Math.sin(a) * d];
  }
  const pts = part[1];
  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  const v = pts[Math.floor(rnd() * pts.length) % pts.length];
  const k = rnd() * 0.8;                           // convexe : tout point entre centre et sommet est dedans
  return [cx + (v[0] - cx) * k, cy + (v[1] - cy) * k];
}

// ------------------------------------------------------------------ dessin
function fillPart(g, part, ox, oy, inset) {
  if (part[0] === 'box') {
    const [, w, h, dx, dy] = part;
    g.fillRect(ox + dx - w / 2 + inset, oy + dy - h / 2 + inset, w - 2 * inset, h - 2 * inset);
  } else if (part[0] === 'circle') {
    const [, r, dx, dy] = part;
    g.fillCircle(ox + dx, oy + dy, r - inset);
  } else {
    const pts = part[1];
    const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
    const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
    g.beginPath();
    pts.forEach(([x, y], i) => {
      const d = Math.hypot(x - cx, y - cy) || 1;
      const k = Math.max(0, (d - inset) / d);      // on rapproche chaque sommet du centre de `inset` px
      const px = ox + cx + (x - cx) * k;
      const py = oy + cy + (y - cy) * k;
      if (i === 0) g.moveTo(px, py); else g.lineTo(px, py);
    });
    g.closePath();
    g.fillPath();
  }
}

function strokePart(g, part, ox, oy) {
  if (part[0] === 'box') {
    const [, w, h, dx, dy] = part;
    g.strokeRect(ox + dx - w / 2, oy + dy - h / 2, w, h);
  } else if (part[0] === 'circle') {
    const [, r, dx, dy] = part;
    g.strokeCircle(ox + dx, oy + dy, r);
  } else {
    g.beginPath();
    part[1].forEach(([x, y], i) => (i === 0 ? g.moveTo(ox + x, oy + y) : g.lineTo(ox + x, oy + y)));
    g.closePath();
    g.strokePath();
  }
}

/** Détails propres à chaque type (repère du meuble décalé de ox, oy). */
function details(g, kind, parts, ox, oy) {
  const [side] = styleOf(kind);
  const p0 = parts[0];
  if (kind === 'barrel') {
    g.lineStyle(2, 0x2a1c12, 0.9);
    g.strokeCircle(ox, oy, p0[1] * 0.7);
    g.strokeCircle(ox, oy, p0[1] * 0.35);
  } else if (kind === 'crate') {
    const [, w, h] = p0;
    g.lineStyle(3, side, 1);
    g.lineBetween(ox - w / 2 + 6, oy - h / 2 + 6, ox + w / 2 - 6, oy + h / 2 - 6);
    g.lineBetween(ox + w / 2 - 6, oy - h / 2 + 6, ox - w / 2 + 6, oy + h / 2 - 6);
  } else if (kind === 'round_table') {
    g.lineStyle(2, side, 0.8);
    g.strokeCircle(ox, oy, p0[1] * 0.55);
  } else if (kind === 'bookshelf') {
    const [, w, h] = p0;
    const books = [0x7a2e2e, 0x2e4a7a, 0x3d6b3a, 0x8a7a3a, 0x5a3a6a];
    for (let x = -w / 2 + 6, i = 0; x < w / 2 - 8; x += 9, i++) {
      g.fillStyle(books[i % books.length], 1);
      g.fillRect(ox + x, oy - h / 2 + 5, 7, h - 10);
    }
  } else if (kind === 'sofa_l') {
    g.fillStyle(side, 1);                          // dossier le long des deux côtés extérieurs
    const [, w, h, dx, dy] = p0;
    g.fillRect(ox + dx - w / 2 + 3, oy + dy - h / 2 + 3, w - 6, 14);
    const [, w2, h2, dx2, dy2] = parts[1];
    g.fillRect(ox + dx2 + w2 / 2 - 17, oy + dy2 - h2 / 2, 14, h2 - 3);
  } else if (kind === 'bed') {
    const [, w, h] = p0;
    g.fillStyle(0xcfc8b8, 1);
    g.fillRect(ox - w / 2 + 10, oy - h / 2 + 8, w - 20, 24);
  } else if (kind === 'wardrobe') {
    const [, , h] = p0;
    g.fillStyle(0x000000, 0.6);
    g.fillRect(ox - 1.5, oy - h / 2 + 4, 3, h - 8);
  } else if (kind === 'fridge') {
    const [, w, h] = p0;
    g.fillStyle(0x6d726c, 1);
    g.fillRect(ox + w / 2 - 12, oy - h / 2 + 10, 4, h / 2 - 6);
  } else if (kind === 'piano') {
    const [, w, h, dx, dy] = p0;                   // clavier : bande blanche + touches noires côté avant
    const x0 = ox + dx - w / 2 + 6;
    const y0 = oy + dy - h / 2 + 4;
    g.fillStyle(0xe8e4d8, 1);
    g.fillRect(x0, y0, w - 12, 14);
    g.fillStyle(0x0b0b0d, 1);
    for (let x = 4; x < w - 16; x += 7) if (x % 21 !== 18) g.fillRect(x0 + x, y0, 3, 8);
  }
}

/** Dessine un type de meuble dans `g` (Graphics hors scène) ; renvoie la taille et l'origine de la texture. */
export function drawKind(g, kind, parts, pad = 4) {
  const [x0, y0, x1, y1] = kindBounds(parts);
  const ox = pad - x0;
  const oy = pad - y0;
  const [side, top] = styleOf(kind);
  g.clear();
  g.fillStyle(side, 1);
  for (const p of parts) fillPart(g, p, ox, oy, 0);
  g.fillStyle(top, 1);
  for (const p of parts) fillPart(g, p, ox, oy, 4);
  details(g, kind, parts, ox, oy);
  g.lineStyle(2, 0x000000, 0.7);
  for (const p of parts) strokePart(g, p, ox, oy);
  const w = Math.ceil(x1 - x0 + 2 * pad);
  const h = Math.ceil(y1 - y0 + 2 * pad);
  return { w, h, originX: ox / w, originY: oy / h };
}
