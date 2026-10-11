# Barricade — contexte pour Claude Code

Mock jouable d'un jeu d'infection multijoueur en navigateur (inspiré de « Tag, you're a ZOMBIE ! »).
Vue de dessus 2D pour l'instant ; une version 3D à la troisième personne est envisagée plus tard.

## Qui travaille avec toi
Ingénieur QA qui connaît Python mais débute en développement de jeu : explique brièvement les notions de
jeu (tick, interpolation, autorité serveur…) quand elles apparaissent, et avance par petites étapes testables.

## Le jeu
- Salon de 24 joueurs max, manche de 2 min 30 (réglable). Un patient zéro tiré au hasard, figé 30 s au début.
- Un zombie qui touche un humain l'infecte. Humains : survivre jusqu'au chrono. Zombies : infecter tout le monde.
- Cœur du jeu : ~75-90 meubles physiques de formes variées (cercles, polygones, formes composées : piano à queue,
  canapé d'angle…, catalogue PROP_KINDS dans game.py) qu'on déplace en les FRAPPANT pour barricader les portes.
  Seuls les coups de ZOMBIE les abîment (20 à 50 coups) ; cassés, ils débloquent les situations figées.
- Humains : pistolet (6 balles) ; MP9 et fusil à pompe à ramasser au sol (8 par manche). Tirs imprécis
  (dispersion + « spray » qui grandit en rafale), dégâts réduits avec la distance. Pas de tir ami.
- Zombies : 300 PV (30 balles), abattus ils réapparaissent 5 s après dans leur salle. Dash au clic droit (10 s).
  Le patient zéro est l'ALPHA : plus gros, plus rapide, sort anti-ralenti (touche E, 5 s, recharge 30 s).
- Ambiance sombre / gore (Walking Dead) ; limite de 24 joueurs.

## Architecture
- `server/` : Python 3.12, FastAPI + WebSocket, physique **pymunk**. État en mémoire, UN seul worker.
  - `app/maps.py` + `app/map_data/*.json` : cartes = données (zones de sol/thème/apparition, murs obliques,
    portes, obstacles, meubles fixes) ; `ville` (défaut), `entrepot`, `manoir`. Format et méthode pour créer une
    carte à partir d'une description : `app/map_data/README.md`. Aperçu PNG : `python tools/render_map.py <nom> --nav`.
  - Navigation des bots : `tcod` (Dijkstra multi-sources + descente de pente) sur une grille générée depuis les murs.
  - `app/game.py` : toute la logique (physique, manches, infection, tir, bots, snapshots). **Aucun I/O** :
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
`MIN_PLAYERS`, `MAX_PLAYERS`, `FILL_TO` (bots pour jouer seul), `MAP` (`ville` | `entrepot` | `manoir` | tout fichier de `app/map_data/`).

## Règles de travail
- Toute règle de jeu va dans `game.py` avec un test dans `tests/test_game.py`.
- Ne casse pas le protocole sans mettre à jour `net.js`, `models.py`, `tests/test_ws.py` ensemble.
- Après un changement visuel, dis honnêtement ce que tu as vérifié (lancé dans le navigateur ou non).
- Ne mets pas de calcul de physique côté client : le client affiche, le serveur décide.

## État actuel
- Serveur : 70 tests verts ; entrepôt, 24 joueurs ≈ 1,6 ms/tick (pire tick ~15 ms) ; ~30 Ko/s par client.
- Client : rendu vérifié dans le navigateur (capture) ; sang/débris « cuits » dans une RenderTexture.
  Musique + sons synthétisés (Web Audio). En dev, `window.__barricade` = { game, net, sound }.
- En ligne : https://barricade.212.227.181.202.sslip.io (Coolify, `docker-compose.coolify.yml`, 24 bots).
  Mise à jour = `git push` sur main : GitHub Actions teste puis déploie (`.github/workflows/ci.yml`).

## Limites connues / pistes (par ordre d'intérêt)
1. Jouer et équilibrer : vitesses, force des coups (`HIT_IMPULSE`), masses des meubles, munitions, durée du gel.
2. Brouillard de guerre côté serveur (aujourd'hui tous les joueurs sont envoyés à tous : triche possible).
3. Minimap, sons, tactile, scores / classement de manche, paramètres de partie modifiables depuis le salon.
4. Bots qui barricadent. Prédiction côté client si la latence gêne.
5. Plus tard : version 3D troisième personne (Three.js + moteur physique Rapier ; le serveur passerait alors à
   Node.js pour partager le même moteur avec le client).
6. Déploiement VPS Ubuntu 24.04 : `docker compose up -d --build` (voir README.md).
