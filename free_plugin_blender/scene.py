"""Putting results into the scene. Main thread only."""

from __future__ import annotations

from pathlib import Path

import bpy


def _node(nodes, node_type):
    return next((n for n in nodes if n.type == node_type), None)


def capture_camera(path: Path) -> Path:
    """OpenGL render of the active camera, saved as PNG — the start frame for image→video/3D."""
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("The scene has no active camera")
    bpy.ops.render.opengl(write_still=False, view_context=False)
    bpy.data.images["Render Result"].save_render(str(path), scene=scene)
    return path


def export_selected_glb(path: Path) -> Path:
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True)
    return path


def import_glb(path: Path, tag: dict | None = None) -> list[str]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    for obj in new:
        for key, value in (tag or {}).items():
            obj[key] = value
    return [o.name for o in new]


def load_image(path: Path, colorspace="sRGB"):
    image = bpy.data.images.load(str(path), check_existing=True)
    image.colorspace_settings.name = colorspace
    return image


def image_to_camera_background(image):
    camera = bpy.context.scene.camera
    if camera is None:
        return False
    bg = camera.data.background_images.new()
    bg.image = image
    camera.data.show_background_images = True
    return True


def image_to_plane(image, name="Generated image"):
    width, height = image.size
    aspect = width / height if height else 1.0
    mesh = bpy.data.meshes.new(name)
    half_w, half_h = aspect, 1.0
    mesh.from_pydata([(-half_w, 0, -half_h), (half_w, 0, -half_h), (half_w, 0, half_h), (-half_w, 0, half_h)],
                     [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new()
    for loop, coord in zip(uv.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
        loop.uv = coord
    obj = bpy.data.objects.new(name, mesh)
    obj.location = bpy.context.scene.cursor.location
    bpy.context.collection.objects.link(obj)

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = _node(nodes, "BSDF_PRINCIPLED")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    mesh.materials.append(material)
    return obj.name


def set_world_hdri(path: Path, strength=1.0):
    scene = bpy.context.scene
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    background = _node(nodes, "BACKGROUND") or nodes.new("ShaderNodeBackground")
    output = _node(nodes, "OUTPUT_WORLD") or nodes.new("ShaderNodeOutputWorld")
    env = _node(nodes, "TEX_ENVIRONMENT") or nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(path), check_existing=True)
    env.location = background.location.x - 300, background.location.y
    links.new(env.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])
    background.inputs["Strength"].default_value = strength
    return world.name


def build_material(obj, name, maps: dict[str, Path], *, tiling=1.0, bump_from_color=False):
    """Principled material from {role: file}. Uses UVs if the mesh has them, else box projection."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = _node(nodes, "BSDF_PRINCIPLED")

    has_uv = obj.type == "MESH" and len(obj.data.uv_layers) > 0
    coords = nodes.new("ShaderNodeTexCoord")
    coords.location = -1100, 0
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = -900, 0
    mapping.inputs["Scale"].default_value = (tiling, tiling, tiling)
    links.new(coords.outputs["UV" if has_uv else "Object"], mapping.inputs["Vector"])

    def texture(role, y, colorspace):
        node = nodes.new("ShaderNodeTexImage")
        node.image = load_image(maps[role], colorspace)
        node.location = -600, y
        if not has_uv:
            node.projection = "BOX"
            node.projection_blend = 0.2
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    color = texture("base_color", 300, "sRGB")
    links.new(color.outputs["Color"], bsdf.inputs["Base Color"])

    if "roughness" in maps:
        rough = texture("roughness", 0, "Non-Color")
        links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

    if "normal" in maps:
        normal_tex = texture("normal", -300, "Non-Color")
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = -250, -300
        links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    elif bump_from_color:
        # Generated textures come as a single albedo: derive relief from its luminance.
        bump = nodes.new("ShaderNodeBump")
        bump.location = -250, -300
        bump.inputs["Strength"].default_value = 0.4
        links.new(color.outputs["Color"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    if obj.type == "MESH":
        if obj.data.materials:
            obj.data.materials[0] = material
        else:
            obj.data.materials.append(material)
    return material.name


def add_movie_strip(path: Path):
    scene = bpy.context.scene
    editor = scene.sequence_editor or scene.sequence_editor_create()
    # Blender 5.0 renamed `sequences` to `strips`.
    strips = editor.strips if hasattr(editor, "strips") else editor.sequences
    used = {s.channel for s in strips}
    channel = next(c for c in range(1, 128) if c not in used and c + 1 not in used)
    strip = strips.new_movie(name=path.stem, filepath=str(path), channel=channel,
                             frame_start=scene.frame_current)
    return strip.name


def local_remesh(obj, voxel_size):
    modifier = obj.modifiers.new("Free Plugin Remesh", "REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = voxel_size
    return modifier.name


def local_lods(obj, ratios=(0.5, 0.25, 0.1)):
    names = []
    for level, ratio in enumerate(ratios, start=1):
        copy = obj.copy()
        copy.data = obj.data.copy()
        copy.name = f"{obj.name}_LOD{level}"
        modifier = copy.modifiers.new("Decimate", "DECIMATE")
        modifier.ratio = ratio
        for collection in obj.users_collection:
            collection.objects.link(copy)
        copy.hide_set(True)
        names.append(copy.name)
    return names
