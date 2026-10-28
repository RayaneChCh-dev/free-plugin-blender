# free-plugin-blender

Extension Blender (4.2+, testée sur 5.2) pour générer **images, matériaux,
vidéos et modèles 3D avec tes propres clés API**, sans abonnement à une
plateforme intermédiaire, et pour **discuter avec Claude dans Blender** sur ton
abonnement Claude (via Claude Code et un add-on MCP).

| Fonction | Fournisseur | Modèle par défaut | Coût indicatif |
|---|---|---|---|
| Texte/image → image | fal.ai | Seedream 4.5 (`fal-ai/bytedance/seedream/v4.5/*`) | ~0,04 $ / image |
| Matériau tileable sur l'objet actif | fal.ai | Seedream 4.5 + relief calculé | ~0,04 $ |
| Texte / vue caméra → vidéo (panneau masqué par défaut) | fal.ai | Kling 3.0 Pro (`fal-ai/kling-video/v3/pro/*`) | ~0,14 $ / s |
| Texte / image / vue caméra → modèle 3D | fal.ai | au choix, voir ci-dessous | 0,02 à 0,53 $ |
| Auto-rig + animations marche/course | fal.ai | Meshy rigging (`fal-ai/meshy/rigging`) | ~0,20 $ |
| Animation : 678 presets Meshy | fal.ai | Meshy rigging + bibliothèque d'animations | ~0,32 $ / preset |
| Animation : mouvement décrit en texte | fal.ai | Hunyuan Motion (`fal-ai/hunyuan-motion`) | ~0,08 $ |
| Copier un mouvement d'un rig à un autre | Blender | — | **gratuit** |
| Retexture d'un modèle | fal.ai, ou Meshy avec ta clé | Meshy retexture (`fal-ai/meshy/retexture`) | voir fal.ai |
| HDRI, textures PBR, **modèles 3D** | Poly Haven | CC0 | **gratuit** |
| Voxel remesh, LOD | Blender | — | **gratuit** |

### Modèles 3D

| Modèle | Entrée | Coût fal.ai | Remarque |
|---|---|---|---|
| **TRELLIS** | image | ~0,02 $ | Le moins cher, idéal pour itérer |
| **TRELLIS 2** | image | ~0,30 $ | Plus fin, UV et remesh propres |
| **Tripo H3.1** | texte ou image | ~0,30 $ | Bonne topologie, PBR |
| **Hunyuan3D 3.1 Pro** | texte ou image | ~0,38 $ (+0,15 $ PBR) | Meilleure qualité de texture |
| Meshy (ta clé) | texte ou image | crédits | Si tu as un abonnement Meshy |

TRELLIS et TRELLIS 2 n'acceptent qu'une image. Avec un prompt texte, le plugin
dessine d'abord une image de référence avec Seedream (+0,04 $), puis génère
le modèle. Avec TRELLIS, un modèle 3D depuis un texte revient donc à environ 0,06 $.

Prix indicatifs relevés en octobre 2026, à vérifier sur
[fal.ai/pricing](https://fal.ai/pricing) et [meshy.ai](https://www.meshy.ai/pricing).

Aucune dépendance : uniquement la bibliothèque standard Python. Le zip fait
environ 110 Ko.

## Installation

```bash
python3 scripts/build.py   # ou : blender --command extension build --source-dir free_plugin_blender --output-dir dist
```

Puis dans Blender : *Edit → Preferences → Get Extensions → ⌄ → Install from Disk…*
→ `dist/free_plugin_blender-0.8.0.zip`. Le panneau est dans la sidebar (N),
onglet **Free Plugin**.

## Configuration (Preferences → Add-ons → Free Plugin Blender)

Les préférences sont organisées en trois étapes :

1. **Claude, avec ton abonnement.** Bouton *Connect my Claude subscription* :
   la connexion se fait dans le navigateur via Claude Code (`claude auth
   login`), sans clé API. L'état s'affiche ensuite (« Claude Pro · ton
   e-mail ») ; *Disconnect* te déconnecte. Si Claude Code n'est pas installé,
   *How to install Claude Code* copie la commande d'installation et ouvre la page.
2. **fal.ai**, pour générer images, matériaux, 3D et vidéos (paiement à
   l'usage). *Get a key* ouvre <https://fal.ai/dashboard/keys>. C'est
   optionnel : le chat, Poly Haven et les outils de maillage marchent sans.
   La clé **Meshy** est facultative : elle sert seulement si tu as des crédits
   Meshy et préfères les utiliser (3D, rig, retexture) au lieu de fal.ai.
3. **Blender MCP**, qui permet à Claude d'agir sur la scène : état du port et
   lien vers l'add-on `mcp-for-blender`.

Les variables d'environnement `FAL_KEY` et `MESHY_API_KEY` fonctionnent aussi.

Le panneau **Vidéo** est masqué par défaut, car c'est la fonction la plus
chère. Coche *Show video panel* dans les préférences pour l'afficher.
L'opérateur `bpy.ops.freeplugin.generate_video` reste appelable depuis un
script ou par Claude.

## Choisir et ajouter des modèles

Chaque section (Image, Vidéo, 3D) de la sidebar a son **menu de modèles**, avec le prix
indicatif. Le panneau Matériau utilise le modèle choisi dans Image. Sous le
menu, **Options** affiche les réglages propres au modèle choisi (durée, ratio,
qualité, seed…), lus dans le schéma publié par fal.ai. Seules les options que
tu modifies sont envoyées ; les autres gardent leur valeur par défaut chez fal.ai.

| Panneau | Modèles inclus |
|---|---|
| Image | Seedream 4.5, Nano Banana, Nano Banana Pro, FLUX.2, Qwen Image, FLUX.1 schnell |
| Vidéo | Kling 3.0 Pro/Standard, Kling 2.5 Turbo, Veo 3.1 / Fast, Seedance 1 Pro, Hailuo 02, Wan 2.2 |
| 3D | TRELLIS, TRELLIS 2, Tripo H3.1, Hunyuan3D 3.1 Pro, Meshy 7 (fal.ai), Meshy (ta clé) |

**Réglages simples** : sous le menu de modèle (sidebar) et en puces dans la barre,
des réglages communs à tous les modèles, traduits vers les vrais champs de chacun :

| Mode | Réglages |
|---|---|
| Image | Ratio, Résolution (1K/2K/4K), Qualité (Low/Medium/High), Format (PNG/JPEG/WebP) |
| 3D | Mode (Preview = forme seule / Full = texturé), Type (Standard / Low-poly / Smart topology), Topologie (triangles / quads), Détail (nombre de polygones), PBR, Texture |
| Vidéo | Durée et résolution (celles que le modèle propose), Ratio, Audio |

*Auto* garde la valeur par défaut du modèle. Un réglage que le modèle choisi ne
sait pas faire est grisé dans la sidebar et absent de la barre ; une valeur
qu'un nouveau modèle n'accepte pas (une durée de 15 s, par exemple) n'est pas
envoyée. Les réglages priment sur la même option dans *Advanced*.

**N'importe quel autre modèle fal.ai** : choisis *Other fal.ai model…*, colle
son identifiant (par exemple `fal-ai/flux/dev`) et clique sur ⟳. Ses options
apparaissent automatiquement.

**L'ajouter au menu pour de bon** : *Preferences → Open my models.json*, puis
*Reload models* :

```json
{
  "image": [
    {"key": "flux_dev", "label": "FLUX.1 dev", "cost": "$0.025 / MP",
     "text": "fal-ai/flux/dev"}
  ],
  "video": [],
  "mesh": []
}
```

`text` est l'endpoint utilisé avec un prompt seul, `image` celui utilisé avec
une image en entrée ; `defaults` pré-règle des options (par exemple
`{"generate_audio": false}`). Une entrée qui reprend la `key` d'un modèle
intégré le remplace.

Pour les mainteneurs : après avoir modifié `free_plugin_blender/data/models.json`,
`python3 scripts/refresh_schemas.py` régénère les schémas embarqués.

## La barre de prompt dans le viewport

En bas de chaque vue 3D, une barre **« Describe the scene you imagine… »**.
Clique dessus : elle s'ouvre en carte avec

- des **onglets de mode** : *Scene builder* (chat avec Claude), *3D Model*,
  *Image*, *Material*, *Video* (si activé), *Animation*, *Assets* (Poly Haven) ;
- la conversation, et **+** en haut à gauche pour en commencer une nouvelle ;
- en haut à droite, l'état ou le prix : cliquer sur une étiquette rouge
  (« Connect Claude », « Add fal.ai key »…) ouvre directement la solution ;
- les objets sélectionnés en **@mentions** (× pour en retirer un) : Claude
  reçoit la sélection avec ton message ;
- **+** pour partir de la vue caméra ou d'une image, et le **menu de modèle**
  avec les prix ; en mode *Scene builder*, le modèle Claude (Opus 5.5 par défaut,
  Fable 5.1, Opus 5, Sonnet 5.5, Sonnet 5, Haiku 5.5) et l'**effort** (Low, Medium par
  défaut, High, XHigh, Max) ;
- le bouton **Send / Generate / Search** (Stop pendant une réponse de Claude).

Entrée envoie, Maj+Entrée va à la ligne, Échap ferme. Pendant la saisie, les
raccourcis de Blender sont suspendus ; un clic ailleurs rend la main à Blender.
La barre se désactive dans les préférences (*Viewport prompt bar*).

## La sidebar

Onglet **Free Plugin** (N) : en-tête d'état (fal.ai, Claude Code, MCP, Meshy),
onglets **Scene · 3D · Image · Video · Animation · Assets**, sections repliables
(3D Model, Auto-Rig, Retexture, Mesh tools, Image, Material…) avec toutes les
options des modèles, et l'historique **Generations**.

## Animation

Onglet **Animation** de la sidebar, et mode *Animation* de la barre. Le
personnage est l'**objet actif** : son maillage ou son armature. Il doit
regarder vers **-Y** dans Blender (exigence de Meshy).

- **Presets** (~0,32 $) : 678 animations de la bibliothèque Meshy (marche,
  course, danse, combat, gestes du quotidien…), avec recherche, catégorie et
  filtre *In place* (mouvements sur place). *Animate* applique le preset choisi.
  - Personnage **sans rig** : Meshy le rigge et l'anime. Le personnage riggé
    remplace le maillage d'origine (caché, pas supprimé) et devient l'objet actif.
  - Personnage **avec rig** : le mouvement est copié sur ce rig, comme une
    nouvelle *action* nommée d'après le preset.
  - fal.ai n'a pas d'endpoint pour animer un rig existant : chaque preset refait
    le rig chez Meshy, d'où le prix.
- **Mouvement libre** (~0,08 $) : décris un mouvement (« a joyful jump »),
  de 0,5 à 12 s. Hunyuan Motion le génère sur un mannequin, puis il est copié
  sur le rig du personnage. Sans rig, le mannequin animé est gardé, au curseur 3D.
  Dans la barre : le texte, la puce *Duration* et la puce du rig visé.
- **Copier un mouvement** (gratuit) : sélectionne l'armature animée, puis
  Ctrl+clic sur celle qui reçoit le mouvement, et *Copy motion*.

Chaque mouvement est une action gardée dans le .blend (*fake user*) : le menu
*Motion* de la section *Character* passe de l'une à l'autre. La copie reconnaît
les noms d'os SMPL, Meshy, Mixamo, Rigify et Unreal ; il faut au moins 8
articulations communes.

## Chat avec Claude

Le mode *Scene builder* de la barre, et la section *Chat with Claude* de
l'onglet Scene, envoient tes messages à **Claude Code**, sur ton abonnement
Claude, sans clé API. Claude agit sur la scène à travers un serveur MCP
Blender : il modélise en Python, inspecte la scène et appelle les opérateurs du
plugin (Poly Haven, génération d'images, de matériaux, 3D…).

Prérequis :
1. [Claude Code](https://claude.com/claude-code) installé, et ton abonnement connecté (bouton *Connect my Claude subscription*).
2. L'add-on Blender de [`mcp-for-blender`](https://pypi.org/project/mcp-for-blender/)
   activé dans Blender (il ouvre le port 9876), et [`uv`](https://docs.astral.sh/uv/)
   installé pour lancer `uvx mcp-for-blender`.

Dans la sidebar, *Transcript* copie toute la
conversation dans le Text Editor, *New* repart de zéro. La conversation est
enregistrée dans le fichier .blend.

Réglages dans *Preferences → Add-ons → Free Plugin Blender* : modèle Claude et
effort (aussi dans la barre et la sidebar), chemin de `claude`, commande et port
du serveur MCP. Plus d'effort : de meilleurs résultats sur les scènes difficiles,
mais des réponses plus lentes et plus d'usage de ton abonnement.

Sécurité : le chat lance `claude -p` avec tous les outils intégrés désactivés
(`--tools ""`), seulement le serveur MCP Blender chargé et autorisé
(`--strict-mcp-config`, `--permission-mode dontAsk`). Ce serveur peut exécuter
du Python dans Blender : c'est ce qui permet à Claude de construire la scène,
mais ce Python a les mêmes droits que Blender sur ta machine.

Si plusieurs Blender sont ouverts, le serveur MCP joint celui qui détient le
port. Chaque Blender a donc un identifiant que Claude vérifie avant de modifier
quoi que ce soit. Pour en piloter plusieurs, donne à chacun son propre port
(add-on MCP et préférence *MCP add-on port*).

## Piloter depuis Claude Code (terminal)

Le même serveur MCP peut être utilisé depuis Claude Code dans le terminal.
Claude appelle alors directement les opérateurs :

```python
bpy.ops.freeplugin.generate_image(prompt="a moroccan riad courtyard at dusk")
bpy.ops.freeplugin.generate_texture(prompt="green zellige tiles")
bpy.ops.freeplugin.generate_3d(prompt="a clay tagine pot", model="trellis")
bpy.ops.freeplugin.generate_video(prompt="slow dolly in", model="kling25_turbo",
                                  options='{"duration": "10"}')
bpy.ops.freeplugin.animate_preset(preset_id=106)   # id de data/animations.json
bpy.ops.freeplugin.generate_motion(prompt="a joyful jump", duration=3)
```

`model` accepte une clé du catalogue ou n'importe quel identifiant fal.ai,
`options` un objet JSON d'options du modèle. Ces opérateurs rendent la main
immédiatement ; le résultat se lit ensuite ici :

```python
import json; json.loads(bpy.context.window_manager.get("free_plugin_tasks", "[]"))
```

## Structure

```
free_plugin_blender/
  __init__.py         enregistrement
  prefs.py            clés, dossier de sortie, accès au catalogue
  account.py          connexion de l'abonnement Claude (claude auth)
  chat.py             chat : claude -p + serveur MCP Blender
  overlay/            barre de prompt du viewport (gpu/blf, champ texte, modal)
  catalog.py          catalogue de modèles (data/models.json + ton models.json)
  params.py           menus de modèles et options générées depuis les schémas
  controls.py         réglages simples → champs de chaque modèle (sans bpy)
  ui_controls.py      ces réglages dans la sidebar et la barre
  data/               models.json, animations.json et schémas fal.ai embarqués
  props.py            réglages du panneau (scene.free_plugin)
  operators.py        un opérateur par bouton (bpy.ops.freeplugin.*)
  animation.py        presets, mouvement libre, copie de mouvement
  presets.py          bibliothèque d'animations Meshy et recherche (sans bpy)
  rigmap.py           articulations humanoïdes d'après les noms d'os (sans bpy)
  retarget.py         copie d'un mouvement d'une armature à une autre
  panels.py           sidebar N
  tasks.py            réseau dans un thread, scène sur le thread principal
  scene.py            import GLB, matériaux, HDRI, plan image, strip vidéo
  net.py              HTTP stdlib, téléchargement, data URI
  providers/          fal.py, fal_schema.py, meshy.py, polyhaven.py (sans bpy)
```

## Développement

- Chaque changement passe par une pull request vers `main`, qui est protégée.
  La marche à suivre est dans le skill [`feature-pr`](.claude/skills/feature-pr/SKILL.md).
- Tests :

  ```bash
  uvx ruff@0.14.0 check .
  python3 -m pytest -q                                           # sans Blender
  python3 scripts/run_blender_tests.py --blender /chemin/blender # Blender sans interface
  python3 scripts/run_gui_tests.py --blender /chemin/blender     # vrais clics, ouvre une fenêtre
  ```

- La CI (GitHub Actions) lance `lint`, `unit-tests` et `blender-tests` sur chaque PR.
- Release : augmenter `version` dans `blender_manifest.toml`, fusionner dans `main`,
  puis pousser le tag `vX.Y.Z`. Le workflow *Release* publie le zip.
- Feuille de route : [docs/ROADMAP.md](docs/ROADMAP.md).

## Licence

GPL-3.0-or-later.
