# Passation : reprendre le travail sur free-plugin-blender

Dernière mise à jour : 2026-10-28 (v0.14.0 publiée). À lire en premier dans une nouvelle session.
Puis lire `CLAUDE.md`, `.claude/skills/feature-pr/SKILL.md` et `docs/ROADMAP.md`.

## 1. Le projet en bref

- Extension Blender (Python stdlib uniquement, Blender 4.2+, testée sur 5.2) :
  génération d'images, de matériaux, de vidéos et de 3D via **fal.ai** (clé de
  l'utilisateur), Poly Haven gratuit, outils locaux, et **chat avec Claude**
  dans Blender via **Claude Code** sur l'abonnement de l'utilisateur
  (`claude -p` + un serveur MCP Blender).
- Dépôt : https://github.com/RayaneChCh-dev/kiln-plugin-blender, dossier local
  `~/free-plugin-blender`. Docs utilisateur en anglais dans `README.md` (nom affiché « Kiln », images dans `docs/assets/`).
- Né de l'analyse de l'add-on Higgsfield (dépôt local séparé, non publié :
  `~/higgsfield-blender-decoded`).

## 2. Règles de travail (non négociables)

- **`main` est protégée** : PR obligatoire, checks `lint`, `unit-tests` et
  `blender-tests` verts, branche à jour, admins inclus. Jamais de push sur `main`.
- Toujours suivre le skill **`feature-pr`** : branche `feat/<feature>` depuis
  `origin/main` → tests → commit → push de la branche → `gh pr create --base main`
  → `gh pr checks --watch` → donner l'URL de la PR à l'utilisateur.
- **L'utilisateur fusionne lui-même** les PR. Ensuite : `git switch main && git pull`,
  supprimer la branche locale, puis **publier la release en poussant le tag**
  `vX.Y.Z` (il doit correspondre à `version` dans `blender_manifest.toml`). Le
  workflow *Release* teste, construit et publie le zip tout seul.
- Une fonctionnalité par PR. Ne pas commencer la suivante avant que la PR courante
  existe et soit verte. Attendre la fusion si la suivante touche les mêmes fichiers.
- L’utilisateur parle français : réponses en français, README en anglais (choix du 2026-10-28),
  code et messages de commit en anglais.
- Commits et PR : fin de message avec les lignes d'attribution demandées par la session.
- L'utilisateur **n'a pas encore de clé fal.ai** : aucune génération réelle n'a été
  testée ; tout passe par des fakes. Ne jamais demander de clé dans le chat.
- **Ne jamais viser le port 9876 en test réel** : le Blender de l'utilisateur
  y écoute souvent (incident passé : un cube `FP_TestCube` créé dans sa scène).
  Utiliser un port isolé (9877) et un profil jetable (`BLENDER_USER_RESOURCES`).

## 3. Historique des versions

| Version | Contenu | État |
|---|---|---|
| 0.1.0 | Image/vidéo/3D fal.ai + Meshy, Poly Haven, outils locaux | publiée |
| 0.2.0 | 3D via fal.ai (TRELLIS, TRELLIS 2, Tripo, Hunyuan), rig via fal.ai | publiée |
| 0.3.0 | Catalogue `data/models.json`, menus de modèles, options lues dans les schémas fal.ai | publiée |
| 0.4.0 | Barre de prompt dans le viewport, chat Claude, compte Claude (PR #2) | publiée |
| 0.5.0 | Modèles Claude précis + effort Medium par défaut (PR #3) | publiée |
| 0.6.0 | Réglages simples par mode (`controls.py`), Meshy 7 via fal.ai (PR #4) | publiée |
| 0.7.0 | Onglet Animation : presets Meshy, mouvement libre, copie (PR #5) | publiée |
| 0.8.0 | Retexture via fal.ai (`fal-ai/meshy/retexture`), Meshy devient facultatif (PR #6) | publiée |
| 0.9.0 | Serveur MCP intégré, 3 modes d'outils, tokens affichés (PR #7) | publiée |
| 0.10.0 | Phase 4 : chat avec clé API (OpenAI PR #8, Gemini PR #9, DeepSeek PR #10) | publiée |
| 0.11.0 | Refonte de la barre du viewport (PR #11) | publiée |
| 0.12.0 | README anglais « Kiln » (PR #13), fix du clipping du chat (PR #14), bibliothèque *My generations* + sortie par défaut `~/Kiln` (`library.py`) | publiée |
| 0.13.0 | Actions après une image : matériau, onglet 3D avec l'image, scène par Claude avec l'image jointe (`attach.py`, `--input-format stream-json` vérifié avec le vrai Claude Code 2.1.312) | publiée |
| 0.14.0 | *Render scene* comme source (image, 3D, vidéo : `scene.render_scene`) ; **+** de l'onglet Scene : capture du viewport sans la barre (`state.hidden`), vue caméra, rendu ou fichier, envoyés à Claude avec le message (`state.chat_images`) ; l'outil MCP `screenshot` masque aussi la barre | publiée |
| 0.14.1 | Fix : une @mention retirée par × revient quand l'objet est désélectionné puis resélectionné (`_mentions`) | PR ouverte |

## 4. Onglet Animation (v0.7.0, publiée)

Fusionnée (PR #5), release v0.7.0 publiée. Ensuite : v0.8.0, retexture via fal.ai (PR `feat/fal-retexture`).

- `presets.py` (sans bpy) : `data/animations.json` (678 presets Meshy), `search()`,
  prix et durées. Régénération du JSON :
  `( set -a; . ~/.config/meshy/meshy.env; set +a; python3 scripts/refresh_animations.py )`
  (charger la clé sans l'afficher).
- `animation.py` : `freeplugin.animate_preset` (`fal-ai/meshy/rigging` avec
  `enable_animation`, ≈ 0,32 $, sortie `animation_glb`), `freeplugin.generate_motion`
  (`fal-ai/hunyuan-motion`, FBX SMPL-H, ≈ 0,08 $), `freeplugin.copy_motion` (gratuit).
  Avec un rig : retarget en nouvelle action puis suppression de l'import, et le rig
  redevient actif (sinon l'import laisse la sélection vide). Sans rig : le personnage
  importé remplace le maillage caché (tag `free_plugin_character`), le mannequin
  Hunyuan est gardé au curseur.
- `rigmap.py`, `retarget.py` : appariement des os et retarget (voir leurs docstrings).
  Vérifié sur données réelles (Hunyuan → `tiziri/rigged.glb`) : 22 articulations.
- UI : onglet `ANIM` de la sidebar, mode `animation` de la barre (puces Duration et rig).
- Tests : `tests/unit/test_presets.py`, `tests/blender/rigs.py` (rigs synthétiques),
  `test_retarget.py`, `test_animation.py`, `tests/gui/test_animation_ui.py`.
- **Non testé** : appels réels à fal.ai (pas de clé). Le format exact de
  `animation_glb` et du FBX Hunyuan vient de la doc fal.ai et de l'exemple public.

### Phase 3 : serveur MCP intégré (v0.9.0, branche `feat/local-mcp`)

Décision de l'utilisateur : `mcp-for-blender` reste **la base (mode par défaut)** ; notre
serveur est une option avancée pour économiser des tokens. Préférence `mcp_mode` :
`EXTERNAL` (défaut) / `BOTH` / `OWN`.

- `mcpserver/protocol.py` et `httpserver.py` (sans bpy) : JSON-RPC MCP (initialize,
  tools/list, tools/call, ping), transport « Streamable HTTP » en JSON seulement
  (pas de SSE, GET → 405), `127.0.0.1`, jeton `Bearer` (`prefs.own_mcp_token`),
  Origin non local refusé.
- `mcpserver/tools.py` : 12 outils. Ceux qui touchent bpy passent par `on_main`
  (file d'attente vidée par un timer, `pump`). `generate` et `assets` attendent la
  tâche dans le thread HTTP, sans bloquer Blender.
- `chat.mcp_servers()` construit `--mcp-config` selon le mode ; `--allowedTools`
  séparés par des virgules ; prompt système plus court en mode `OWN`.
- **Vérifié avec le vrai Claude Code 2.1.312** (Haiku, Blender jetable, mode OWN) :
  serveur `connected`, `scene_summary` puis `add_object` appelés, objet créé.
- Pas encore mesuré : l'écart de tokens réel entre les modes (le plugin l'affiche
  sous le chat : *Last answer*).

### Phase 4 : fournisseurs à clé API (v0.10.0, publiée à la fin de la phase)

- Préférence `chat_provider` : `CLAUDE` (défaut, Claude Code) / `OPENAI` / `GEMINI` / `DEEPSEEK`. Par
  fournisseur : `<nom>_key` et `<nom>_model` dans les préférences (vide : le plus récent),
  variables d'env dans `PROVIDERS[...]["key_env"]`. Ajouter un fournisseur = une entrée
  `PROVIDERS` + un item `CHAT_PROVIDERS` + les deux propriétés.
- `providers/openai_compat.py` (sans bpy) : Chat Completions + tools, `GET /models`
  filtré (`chat_models`, tri par version), `reasoning_effort` retiré si le modèle le
  refuse. Un seul adaptateur pour la suite : Gemini (endpoint compatible OpenAI),
  DeepSeek, OpenRouter, Ollama = surtout des entrées de `PROVIDERS`.
- `agent.py` (sans bpy) : boucle modèle → `tool_calls` → messages `tool` ; images
  (capture) renvoyées dans un message user. Chaque appel d'outil reçoit sa réponse
  avant un arrêt (exigence de l'API).
- `mcpserver.call_blocks()` / `acquire()` / `release()` : l'agent appelle les
  mêmes outils en interne ; la pompe du thread principal tourne tant qu'il travaille.
- Historique API (`api_history`) sauvé dans le .blend sans les images.
- **Non testé** : un vrai appel OpenAI (pas de clé). Tout passe par un faux API.

### Refonte de la barre du viewport (branche `feat/bar-redesign`)

Phase 4 arrêtée par l'utilisateur après DeepSeek (OpenRouter/Ollama « plus tard »).
v0.10.0 publiée (phase 4, sans la nouvelle barre : tag poussé avant la fusion de PR #11). La refonte sort en v0.11.0.

- Puree évalué et écarté (binaires compilés, PyAV, `moderngl` OpenGL, Blender 5.1+,
  API instable) : on garde notre rendu `gpu`/`blf`.
- Design validé par l'utilisateur : maquette https://claude.ai/artifact/VwrG9hUpbh6YCwo3La2mrV
  (planches Après, États, Avant, et captures de l'implémentation).
- `overlay/richtext.py` (sans bpy) : Markdown léger et retour à la ligne par style ;
  gras = deuxième passe décalée (Blender n'a qu'une graisse d'Inter, `blf` sans poids).
- `overlay/thread.py` (sans bpy) : appels d'outils groupés, avatar par réponse.
- `overlay/__init__.py` : en-tête à onglets, bandeau (`_banner`, depuis `_info`),
  ligne d'état (`_live`), champ avec bouton rond, scissor GPU pour le fil,
  `_span()` centre la carte hors barre d'outils et sidebar.
- Captures : script `capture.py` dans le scratchpad de la session (Blender jetable,
  `screenshot_area`) ; le splash se coupe par `show_splash = False` + `save_userpref`.

### Ensuite (roadmap)

- Gemini fait (thought signatures : `extra_content` gardé). DeepSeek fait
  (`reasoning_content` gardé, `effort` propre, `images: False`, liste `fallback`).
  Changer de fournisseur remet `api_history` à zéro (`api_provider`).
  Reste OpenRouter / Ollama, puis release de la phase (v0.10.0).
- Sketchfab / Poly Pizza et un `look` annoté dans nos outils, si le mode OWN montre
  qu'ils manquent.

## 5. Architecture (fichiers clés)

```
free_plugin_blender/
  __init__.py        enregistrement (ordre : props, classes, catalog.configure, tasks, params, chat, overlay)
  prefs.py           préférences en étapes : Claude, fal.ai (+ Meshy optionnel), MCP, affichage, modèles
  props.py           scene.free_plugin (+ choices pour controls)
  catalog.py         data/models.json + models.json utilisateur ; schémas data/schemas/*.json
  params.py          menus de modèles par slot (image, video, mesh), options Advanced générées
  controls.py        réglages simples → champs du modèle (sans bpy) ; ui_controls.py pour l'UI
  operators.py       générations (_ModelChoice.run : schéma → options → controls → payload)
  providers/         fal.py, fal_schema.py, meshy.py, polyhaven.py (sans bpy)
  mcpserver/         serveur MCP intégré (protocol.py, httpserver.py sans bpy ; tools.py)
  chat.py            claude -p (--tools "", --strict-mcp-config, --allowedTools selon le mode,
                     --permission-mode dontAsk, --model, --effort, --resume), identifiant d'instance
  account.py         claude auth status/login --claudeai/logout
  claude_models.py   modèles Claude exacts et efforts (sans bpy)
  overlay/           barre du viewport (gpu/blf) : field.py (sans bpy), gfx.py, __init__.py (modal)
  tasks.py           threads réseau + file d'attente sur le thread principal ; état dans wm["free_plugin_tasks"]
  animation.py       opérateurs de l'onglet Animation ; presets.py (sans bpy)
  rigmap.py, retarget.py, data/animations.json
```

Schémas fal.ai : `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>`.
Régénérer les schémas embarqués avec `python3 scripts/refresh_schemas.py` après
toute modification de `data/models.json`.

## 6. Tests et outils

```bash
uvx ruff@0.14.0 check .
python3 -m pytest -q                                                   # 100 passent
python3 scripts/run_blender_tests.py --blender ~/.local/opt/blender-5.2.2-linux-x64/blender
python3 scripts/run_gui_tests.py --blender ~/.local/opt/blender-5.2.2-linux-x64/blender   # fenêtre, pas en CI
```

- Blender local : `~/.local/opt/blender-5.2.2-linux-x64/blender` ; la CI utilise 5.2.3.
- Faux `claude` : `tests/fixtures/fakeclaude/claude`, état dans `$FAKE_CLAUDE_STATE`.
  Le code `GOOD` connecte le compte ; un message contenant « slow » attend 30 s.
- Faux fal.ai et Poly Haven : `tests/blender/fakes.py`.

## 7. Pièges déjà rencontrés

- **Menus et explorateur de fichiers ouverts depuis le modal de la barre** : ils ne
  s'affichent jamais. Il faut les ouvrir juste après, via `bpy.app.timers`, avec
  `temp_override(window, area, region)` (voir `_open_menu` et `overlay_browse`).
- **Tests à vrais clics** (`--enable-event-simulate`) : pas plus d'une douzaine
  d'événements par tick, sinon la boucle d'événements de Blender se bloque côté C.
  Une touche par étape pour les répétitions. `FileSelectParams.directory` attend
  des `bytes`.
- Le contexte `bpy.context` est restreint pendant `register()` : lire la scène
  via un timer. Les menus Blender ont des accélérateurs automatiques (première
  lettre) : les tests GUI s'en servent (« H » pour Haiku 5.5, « C » pour Camera view).
- **Variable masquée** : dans `_draw_card`, ne jamais réutiliser `width` (largeur
  de la carte) ; un test de mise en page le vérifie.
- Les enums des préférences ont des numéros explicites (100+, 200+), pour qu'une
  ancienne valeur sauvegardée ne tombe pas sur un autre modèle.
- La description d'une permission du manifeste doit faire 64 caractères au plus et
  ne pas finir par un point (`scripts/build.py` le vérifie).
- La release v0.2.0 avait ce problème (67 caractères) : elle s'installait mais
  échouait à `extension validate`. Corrigé depuis la 0.3.0.
