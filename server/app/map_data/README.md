# Cartes de Barricade

Une carte = un fichier JSON ici (`<nom>.json`). Elle est choisie avec la variable `MAP=<nom>` (défaut : `ville`).
La physique, la navigation des bots et l'affichage se déduisent du fichier : **rien d'autre à régler**.

## Créer une carte à partir d'une description
1. Décrire la carte en langage naturel à Claude (quartiers, bâtiments, pièces, ambiance, où apparaissent les zombies).
2. Claude écrit le JSON, puis le vérifie :
   ```bat
   cd server
   python tools/render_map.py <nom> --nav     :: aperçu PNG (cases rouges = infranchissables pour les bots)
   python -m pytest -q                        :: chaque carte : pièces atteignables, portes valides, apparitions possibles
   ```
3. On joue, on ajuste la description, on recommence.

## Format
Coordonnées en pixels du monde, origine en haut à gauche, x vers la droite, y vers le bas. Angles en degrés.

```jsonc
{
  "name": "ville",                 // = nom du fichier
  "description": "…",              // la description d'origine (pour mémoire)
  "size": [5200, 3600],            // largeur, hauteur (la bordure est ajoutée automatiquement)
  "base": "grass",                 // sol par défaut sous toutes les zones

  "areas": [                       // dessinées dans l'ordre (les suivantes recouvrent les précédentes)
    {"id": "cuisine", "rect": [x0, y0, x1, y1], "ground": "tile", "theme": "kitchen", "spawn": "human"},
    {"id": "salon", "poly": [[x, y], …], "ground": "carpet", "theme": "living", "spawn": "human"},
    {"id": "tombes", "rect": […], "ground": "cemetery", "spawn": "zombie"}
  ],
  "walls": [                       // lignes brisées, n'importe quel angle ; bouts arrondis
    {"path": [[x, y], [x, y], …], "closed": true, "t": 24, "style": "brick"},
    {"rect": [x0, y0, x1, y1], "t": 10, "style": "fence"}
  ],
  "doors": [[x, y], [x, y, 150]],  // un point SUR un mur ; largeur 110 par défaut (≥ 100 pour les bots)
  "obstacles": [                   // fixes et indestructibles
    {"kind": "tree", "at": [x, y], "r": 34},
    {"kind": "grave", "at": [x, y], "size": [34, 18], "angle": 8}
  ],
  "props": [{"kind": "car", "at": [x, y], "angle": 90}]   // meubles posés à la main, en plus des thèmes
}
```

| Champ | Valeurs |
|---|---|
| `ground` | floor, wood, tile, carpet, stone, straw, concrete, grass, asphalt, sidewalk, dirt, field, gravel, cemetery |
| `theme` (mobilier auto) | living, dining, bedroom, kitchen, bathroom, library, hall, office, shop, storage, garage, barn, chapel, farmyard, garden, street, mixed |
| `spawn` | `human` (apparition des humains, au moins une zone), `zombie` (patient zéro et réapparitions, au moins une) |
| `style` (murs) | brick, wood, stone, concrete, fence, iron, hedge |
| `kind` (obstacles) | tree, rock, well, silo, pillar, pump (cercles de rayon `r`), grave (bloc `size`, `angle`) |
| `kind` (meubles) | chair, barrel, crate, table, round_table, bookshelf, sofa_l, bed, wardrobe, fridge, piano, stove, counter, bathtub, hay_bale, pew, dumpster, car, armchair, coffin, oval_table, hex_table, corner_cabinet, desk_l, sofa_u, washing_machine, tv_stand, plant_pot, drum_kit, log_pile, tractor, altar, metal_shelf, safe |

Les thèmes et les meubles sont définis dans `app/game.py` (`THEMES`, `PROP_KINDS`).

## Règles pratiques
- Murs : 20 à 30 d'épaisseur pour un bâtiment, 8 à 10 pour une clôture. Les murs intérieurs partent des murs
  extérieurs (les bouts arrondis se chevauchent, pas de trou).
- Portes : au moins 100 de large (sinon les bots ne passent pas : le test de la carte échoue).
- Une pièce = une zone avec un `theme` : le mobilier y est tiré au hasard, loin des portes et des murs.
- Prévoir plusieurs entrées par bâtiment et des culs-de-sac : c'est là que les barricades deviennent intéressantes.
