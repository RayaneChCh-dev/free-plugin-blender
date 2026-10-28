# Passation : reprendre le travail sur free-plugin-blender

Dernière mise à jour : 2026-10-28. À lire en premier dans une nouvelle session.
Puis lire `CLAUDE.md`, `.claude/skills/feature-pr/SKILL.md` et `docs/ROADMAP.md`.

## 1. Le projet en bref

- Extension Blender (Python stdlib uniquement, Blender 4.2+, testée sur 5.2) :
  génération d'images, de matériaux, de vidéos et de 3D via **fal.ai** (clé de
  l'utilisateur), Poly Haven gratuit, outils locaux, et **chat avec Claude**
  dans Blender via **Claude Code** sur l'abonnement de l'utilisateur
  (`claude -p` + un serveur MCP Blender).
- Dépôt : https://github.com/RayaneChCh-dev/free-plugin-blender, dossier local
  `~/free-plugin-blender`. Docs utilisateur en français dans `README.md`.
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
- L'utilisateur parle français : réponses et docs utilisateur en français,
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
| 0.7.0 | Onglet Animation : presets Meshy, mouvement libre, copie (branche `feat/animation-tab`) | PR ouverte |

## 4. Dernier travail : onglet Animation (v0.7.0, branche `feat/animation-tab`)

PR ouverte, à fusionner par l'utilisateur, puis tag `v0.7.0`.

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

### Ensuite (roadmap)

- **Bonus noté** : `fal-ai/meshy/retexture` existe. La retexture peut passer par
  fal.ai au lieu d'exiger une clé Meshy (aujourd'hui `meshy.py`, direct).
- **Phase 3** : notre propre serveur MCP local avec des outils de haut niveau
  (résumé de scène, primitives, matériaux, rendu, capture, génération, Poly Haven,
  Python en dernier recours). Il remplace la dépendance à `mcp-for-blender` et le
  port partagé.
- **Phase 4** : autres fournisseurs avec clé API (ordre validé : OpenAI → Gemini →
  DeepSeek → OpenRouter/Ollama). La boucle d'agent tourne dans le plugin avec les
  outils de la phase 3. Listes de modèles lues en direct, effort Medium par défaut.

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
  chat.py            claude -p (--tools "", --strict-mcp-config, --allowedTools mcp__blender,
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
python3 -m pytest -q                                                   # 84 passent
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
