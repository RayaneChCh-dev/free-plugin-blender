# free-plugin-blender

Extension Blender (4.2+, testée sur 5.2) pour générer **images, matériaux,
vidéos et modèles 3D avec tes propres clés API**, sans abonnement à une
plateforme intermédiaire. Le pilotage de Blender par l'IA passe par **Claude
Code** (ton abonnement Claude) et un add-on MCP.

| Fonction | Fournisseur | Modèle par défaut | Coût indicatif |
|---|---|---|---|
| Texte/image → image | fal.ai | Seedream 4.5 (`fal-ai/bytedance/seedream/v4.5/*`) | ~0,04 $ / image |
| Matériau tileable sur l'objet actif | fal.ai | Seedream 4.5 + relief calculé | ~0,04 $ |
| Texte / vue caméra → vidéo (dans le Video Sequencer) | fal.ai | Kling 3.0 Pro (`fal-ai/kling-video/v3/pro/*`) | ~0,14 $ / s |
| Texte / image / vue caméra → modèle 3D texturé | Meshy | latest (Meshy 7.x) | crédits Meshy |
| Retexture, auto-rig (+ marche/course) | Meshy | — | crédits Meshy |
| HDRI → monde, textures PBR → matériau | Poly Haven | CC0 | **gratuit** |
| Voxel remesh, LOD | Blender | — | **gratuit** |

Prix indicatifs relevés en octobre 2026, à vérifier sur
[fal.ai/pricing](https://fal.ai/pricing) et [meshy.ai](https://www.meshy.ai/pricing).

Aucune dépendance : uniquement la bibliothèque standard Python. Le zip fait
moins de 20 Ko.

## Installation

```bash
python3 scripts/build.py   # ou : blender --command extension build --source-dir free_plugin_blender --output-dir dist
```

Puis dans Blender : *Edit → Preferences → Get Extensions → ⌄ → Install from Disk…*
→ `dist/free_plugin_blender-0.1.0.zip`. Le panneau est dans la sidebar (N),
onglet **Free Plugin**.

## Clés API

*Preferences → Add-ons → Free Plugin Blender* :

- **fal.ai** : créer une clé sur <https://fal.ai/dashboard/keys>. Facturation à l'usage.
- **Meshy** : <https://www.meshy.ai/settings/api>.

Les variables d'environnement `FAL_KEY` et `MESHY_API_KEY` fonctionnent aussi
et ont l'avantage de ne pas être enregistrées dans les préférences Blender.

Le panneau **Vidéo** est masqué par défaut, car c'est la fonction la plus
chère. Coche *Show video panel* dans les préférences pour l'afficher.
L'opérateur `bpy.ops.freeplugin.generate_video` reste appelable depuis un
script ou par Claude.

Tu peux changer de modèle sans toucher au code : les identifiants fal.ai sont
modifiables dans les préférences, par exemple
`fal-ai/bytedance/seedream/v5/...` ou un modèle Veo. Les modèles vidéo
non-Kling reçoivent l'image de départ dans `image_url`.

## Piloter avec Claude Code

Installe un add-on MCP pour Blender (par exemple l'extension officielle
**MCP** de Blender Lab, ou `blender-mcp`), connecte-le à Claude Code, puis
demande par exemple : « génère une texture de zellige et applique-la au sol ».
Claude appelle les opérateurs :

```python
bpy.ops.freeplugin.generate_image(prompt="a moroccan riad courtyard at dusk")
bpy.ops.freeplugin.generate_texture(prompt="green zellige tiles")
bpy.ops.freeplugin.generate_3d(prompt="a clay tagine pot")
```

Ils rendent la main immédiatement. Le résultat se lit ensuite ici :

```python
import json; json.loads(bpy.context.window_manager.get("free_plugin_tasks", "[]"))
```

## Structure

```
free_plugin_blender/
  __init__.py         enregistrement
  prefs.py            clés, identifiants de modèles, dossier de sortie
  props.py            réglages du panneau (scene.free_plugin)
  operators.py        un opérateur par bouton (bpy.ops.freeplugin.*)
  panels.py           sidebar N
  tasks.py            réseau dans un thread, scène sur le thread principal
  scene.py            import GLB, matériaux, HDRI, plan image, strip vidéo
  net.py              HTTP stdlib, téléchargement, data URI
  providers/          fal.py, meshy.py, polyhaven.py (sans bpy)
```

## Licence

GPL-3.0-or-later.
