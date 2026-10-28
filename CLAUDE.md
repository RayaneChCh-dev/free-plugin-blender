# free-plugin-blender

Blender extension (Python, stdlib only) in `free_plugin_blender/`. User docs are in
`README.md` (French). The plan of upcoming work is `docs/ROADMAP.md`.

## Every change goes through a pull request

`main` is protected. For any change, follow the `feature-pr` skill
(`.claude/skills/feature-pr/SKILL.md`): `feat/<feature>` branch from main, tests,
PR to main, PR checked and green before the next feature.

## Tests

```bash
uvx ruff@0.14.0 check .
python3 -m pytest -q                                   # tests/unit, no Blender
python3 scripts/run_blender_tests.py --blender <path>  # tests/blender, headless Blender
python3 scripts/run_gui_tests.py --blender <path>      # tests/gui, real clicks; needs a display, not in CI
```

Blender tests run in a throwaway profile (`BLENDER_USER_RESOURCES`), never the
user's real Blender. Never point a live test at port 9876: the user's own Blender
may be listening there.

## Conventions

- Modules under `providers/`, `catalog.py`, `overlay/field.py`, `presets.py`, `rigmap.py`,
  `mcpserver/protocol.py` and `mcpserver/httpserver.py` must not import bpy.
- Network calls run on worker threads (`tasks.run`); scene changes run on the main thread.
- Release: bump the manifest version, merge to main, then push the tag `vX.Y.Z`.
  The Release workflow publishes the zip.
