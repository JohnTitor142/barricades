# Barricade — mock jouable (vue de dessus 2D)

Jeu d'infection multijoueur dans le navigateur : un zombie au hasard, les humains survivent jusqu'à la fin du
chrono en **barricadant les portes avec les meubles** ; les zombies gagnent si tous les joueurs sont infectés.
Serveur Python (FastAPI + WebSocket + physique **pymunk**), client Phaser 3.

## Règles du mock
- **Salon de 24 joueurs max.** Manche de 5 min (`ROUND_SECONDS`).
- Début de manche : un joueur est tiré au hasard (« patient zéro »), **figé 10 s** (`FREEZE_SECONDS`) pour laisser
  le temps de barricader. Les joueurs qui arrivent en cours de manche rejoignent les zombies.
- **Un zombie qui touche un humain l'infecte** (le nouveau zombie est figé 1 s).
- **Frapper** (Espace / clic droit, tout le monde) : fait glisser les meubles devant soi. Une chaise part loin,
  une armoire bouge à peine : il faut plusieurs coups. *Marcher* contre un meuble ne le déplace presque pas.
- **Pistolet** (humains, clic gauche) : 6 balles puis rechargement de 2 s. Une balle **pousse les meubles** et
  **ralentit un zombie** pendant 1,5 s. Pas de tir ami : les balles traversent les humains.
- Un zombie qui clique frappe (pas d'arme à feu).
- Carte : 6 pièces reliées par des portes de 120 px, ~83 meubles de 6 types (chaise, caisse, table, canapé, lit,
  armoire). Les meubles sont remis en place à chaque manche.
- Ambiance : obscurité avec halo autour du joueur, sang aux infections et aux tirs.

## Lancer en local
```bash
# Terminal 1 : serveur (FILL_TO=8 ajoute des bots pour jouer seul ; les bots zombies savent chercher et frapper)
cd server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
FILL_TO=8 uvicorn app.main:app --reload --port 8000

# Terminal 2 : client -> http://localhost:5173
cd client && npm install && npm run dev
```
Ouvrez plusieurs onglets pour jouer à plusieurs. Avec `FILL_TO=8`, un seul onglet suffit pour tester.

## Réglages (variables d'environnement du serveur, voir `.env.example`)
`ROUND_SECONDS`, `FREEZE_SECONDS`, `INTERMISSION_SECONDS`, `MIN_PLAYERS`, `MAX_PLAYERS`, `FILL_TO`.
Les constantes de gameplay (vitesses, impulsion des coups, masse des meubles, munitions…) sont en tête de
`server/app/game.py`.

## Tests
```bash
cd server && pytest -q                      # 30 tests : règles, physique, bots, WebSocket
ruff check .
python tools/bots.py --n 24 --seconds 30    # charge réseau : 24 vrais clients (serveur lancé)
cd ../client && npm test                    # interpolation réseau du client
```
Mesures sur la machine de développement : 24 joueurs + 83 meubles ≈ 0,7 ms de simulation par tick (budget 33 ms),
~35 Ko/s par client, ~11 % d'un cœur avec 24 clients réseau.

## Déploiement VPS (Ubuntu 24.04)
Identique au projet précédent : installer Docker (dépôt officiel), `ufw allow 80,443`, puis
```bash
cp .env.example .env        # DOMAIN=jeu.mondomaine.fr (ou DOMAIN=:80 pour un test par IP)
docker compose up -d --build
curl http://localhost/health
```

## Architecture
```
Navigateur (Phaser) ──ws──► Caddy ──► FastAPI /ws ──► World (game.py : pymunk + règles, en mémoire)
   ▲ intentions : dx, dy, angle de visée, act(hit|shoot)        │
   └────── 30 snapshots/s : joueurs + SEULEMENT les meubles qui bougent ◄──┘
```
- `server/app/game.py` : carte, physique, manches, infection, tir, bots, snapshots (aucun I/O, testable).
- `server/app/main.py` : WebSocket, boucle à tick fixe (30 Hz, physique 60 Hz), limitation de débit.
- `client/src/net.js` : WebSocket + interpolation (affichage à t-100 ms).
- `client/src/scenes/GameScene.js` : rendu, éclairage, saisie, interface.

## Limites connues
- **Rendu non vérifié dans un navigateur par l'auteur** : la couche réseau du client a été testée contre le vrai
  serveur (Node), mais l'aspect visuel, la sensation de jeu et l'équilibrage sont à valider en jouant.
- Tous les joueurs sont envoyés à tous (pas de brouillard de guerre côté serveur) : un client modifié pourrait
  voir à travers les murs. L'obscurité est purement visuelle.
- Pas de prédiction côté client : le déplacement a la latence réseau (acceptable en vue de dessus, à revoir en 3D).
- Pas de tactile, pas de son, pas de comptes ni de scores.
- Les bots sont des sparring-partners simples (pas de barricades de leur part).
