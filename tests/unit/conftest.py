"""Load the add-on's bpy-free modules under a stand-in package.

The real package's __init__ imports bpy, so importing `free_plugin_blender`
outside Blender fails. Registering an empty package with the right __path__
lets `fpb.providers.fal` and friends resolve their relative imports.
"""

import sys
import types
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "free_plugin_blender"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

for name, path in (("fpb", PKG), ("fpb.providers", PKG / "providers"), ("fpb.overlay", PKG / "overlay"),
                   ("fpb.mcpserver", PKG / "mcpserver")):
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
