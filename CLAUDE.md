# Barricade — contexte pour Claude Code

Mock jouable d'un jeu d'infection multijoueur en navigateur (inspiré de « Tag, you're a ZOMBIE ! »).
Vue de dessus 2D pour l'instant ; une version 3D à la troisième personne est envisagée plus tard.

## Qui travaille avec toi
Ingénieur QA qui connaît Python mais débute en développement de jeu : explique brièvement les notions de
jeu (tick, interpolation, autorité serveur…) quand elles apparaissent, et avance par petites étapes testables.

## Le jeu
- Salon de 24 joueurs max, manche de 5 min (réglable). Un patient zéro tiré au hasard, figé 10 s au début.
- Un zombie qui touche un humain l'infecte. Humains : survivre jusqu'au chrono. Zombies : infecter tout le monde.
- Cœur du jeu : ~83 meubles physiques qu'on déplace en les FRAPPANT pour barricader les portes.
- Humains : pistolet (6 balles) qui pousse les meubles et ralentit les zombies. Pas de tir ami.
- Ambiance sombre / gore (Walking Dead) ; limite de 24 joueurs.

## Architecture
- `server/` : Python 3.12, FastAPI + WebSocket, physique **pymunk**. État en mémoire, UN seul worker.
  - `app/game.py` : toute la logique (carte, physique, manches, infection, tir, bots, snapshots). **Aucun I/O** :
    reste pur et testable. Constantes de gameplay en tête de fichier.
  - `app/main.py` : WebSocket, boucle à tick fixe 30 Hz (physique 60 Hz), limitation de débit.
  - `app/models.py` : validation Pydantic des messages entrants (ne jamais faire confiance au client).
  - `tests/` : pytest (règles, physique, bots, WebSocket). `tools/bots.py` : charge réseau.
- `client/` : Phaser 3 + Vite. `src/net.js` (WebSocket + interpolation à t-100 ms), `src/scenes/GameScene.js`
  (rendu, éclairage, saisie, HUD). `test/` : tests Node de l'interpolation.
- Le serveur fait AUTORITÉ : les clients n'envoient que des intentions (direction, angle, hit/shoot).
- Les snapshots n'envoient que les meubles qui bougent (+ resynchro complète toutes les 3 s).

## Commandes (Windows, invite `cmd`, depuis la racine du projet)
```bat
:: Tout lancer d'un coup (serveur + 8 bots + client + navigateur)
start-windows.bat

:: Serveur seul
cd server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
set FILL_TO=8
python -m uvicorn app.main:app --reload --port 8000

:: Tests et lint (OBLIGATOIRES avant de conclure une modification serveur)
python -m pytest -q
ruff check .

:: Client
cd client
npm install
npm run dev        :: http://localhost:5173 (le proxy Vite relaie /ws vers :8000)
npm test           :: interpolation
npm run build
```
Réglages serveur par variables d'environnement : `ROUND_SECONDS`, `FREEZE_SECONDS`, `INTERMISSION_SECONDS`,
`MIN_PLAYERS`, `MAX_PLAYERS`, `FILL_TO` (bots pour jouer seul).

## Règles de travail
- Toute règle de jeu va dans `game.py` avec un test dans `tests/test_game.py`.
- Ne casse pas le protocole sans mettre à jour `net.js`, `models.py`, `tests/test_ws.py` ensemble.
- Après un changement visuel, dis honnêtement ce que tu as vérifié (lancé dans le navigateur ou non).
- Ne mets pas de calcul de physique côté client : le client affiche, le serveur décide.

## État actuel (à confirmer en jouant)
- Serveur : 30 tests verts ; 24 joueurs + 83 meubles ≈ 0,7 ms/tick ; ~35 Ko/s par client.
- Client : compile, couche réseau testée contre le vrai serveur ; **rendu et sensation de jeu jamais vus**
  dans un navigateur par l'auteur initial. C'est la première chose à vérifier.

## Limites connues / pistes (par ordre d'intérêt)
1. Jouer et équilibrer : vitesses, force des coups (`HIT_IMPULSE`), masses des meubles, munitions, durée du gel.
2. Brouillard de guerre côté serveur (aujourd'hui tous les joueurs sont envoyés à tous : triche possible).
3. Minimap, sons, tactile, scores / classement de manche, paramètres de partie modifiables depuis le salon.
4. Bots qui barricadent. Prédiction côté client si la latence gêne.
5. Plus tard : version 3D troisième personne (Three.js + moteur physique Rapier ; le serveur passerait alors à
   Node.js pour partager le même moteur avec le client).
6. Déploiement VPS Ubuntu 24.04 : `docker compose up -d --build` (voir README.md).
