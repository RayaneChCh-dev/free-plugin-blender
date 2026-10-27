# free-plugin-blender

Extension Blender (4.2+, testée sur 5.2) pour générer **images, matériaux,
vidéos et modèles 3D avec tes propres clés API**, sans abonnement à une
plateforme intermédiaire. Le pilotage de Blender par l'IA passe par **Claude
Code** (ton abonnement Claude) et un add-on MCP.

| Fonction | Fournisseur | Modèle par défaut | Coût indicatif |
|---|---|---|---|
| Texte/image → image | fal.ai | Seedream 4.5 (`fal-ai/bytedance/seedream/v4.5/*`) | ~0,04 $ / image |
| Matériau tileable sur l'objet actif | fal.ai | Seedream 4.5 + relief calculé | ~0,04 $ |
| Texte / vue caméra → vidéo (panneau masqué par défaut) | fal.ai | Kling 3.0 Pro (`fal-ai/kling-video/v3/pro/*`) | ~0,14 $ / s |
| Texte / image / vue caméra → modèle 3D | fal.ai | au choix, voir ci-dessous | 0,02 à 0,53 $ |
| Auto-rig + animations marche/course | fal.ai | Meshy rigging (`fal-ai/meshy/rigging`) | ~0,20 $ |
| Retexture d'un modèle | Meshy (clé optionnelle) | — | crédits Meshy |
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
moins de 20 Ko.

## Installation

```bash
python3 scripts/build.py   # ou : blender --command extension build --source-dir free_plugin_blender --output-dir dist
```

Puis dans Blender : *Edit → Preferences → Get Extensions → ⌄ → Install from Disk…*
→ `dist/free_plugin_blender-0.2.0.zip`. Le panneau est dans la sidebar (N),
onglet **Free Plugin**.

## Clés API

*Preferences → Add-ons → Free Plugin Blender* :

- **fal.ai** : créer une clé sur <https://fal.ai/dashboard/keys>. Facturation à l'usage.
- **Meshy** (optionnel, seulement pour la retexture ou si tu as des crédits) : <https://www.meshy.ai/settings/api>.

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
bpy.ops.freeplugin.generate_3d(prompt="a clay tagine pot", provider="TRELLIS")  # TRELLIS2, TRIPO, HUNYUAN, MESHY
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
  providers/          fal.py (image, vidéo, 3D, rig), meshy.py, polyhaven.py (sans bpy)
```

## Licence

GPL-3.0-or-later.
