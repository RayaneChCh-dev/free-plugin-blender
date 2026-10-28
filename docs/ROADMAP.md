# Roadmap

Each phase ships as one or more `feat/…` pull requests (see the `feature-pr` skill).

## Phase 0: how we work (done, v0.4.0)

- `feature-pr` skill: branch `feat/<feature>` from main → tests → PR to main → PR
  checked and green before the next feature.
- CI on every PR: `lint` (ruff), `unit-tests` (pytest, no Blender), `blender-tests`
  (headless Blender 5.2 LTS: build, `extension validate`, install, run `tests/blender`).
- CD: pushing a tag `vX.Y.Z` on main publishes the GitHub release with the zip.
- `main` protected: pull request and passing checks required, admins included.

Then: v0.4.0 (viewport prompt bar, chat with Claude, Claude account) through the same flow.

## Phase 1: Claude models and effort (done, v0.5.0)

- Precise model menu: Fable 5.1, Opus 5.5, Opus 5, Sonnet 5.5, Sonnet 5, Haiku 5.5
  (`claude --model <id>`).
- Effort Low / Medium / High / XHigh / Max (`claude --effort`), **Medium by default**.

## Phase 2: simple controls per mode (v0.6.0), Animation tab (v0.7.0)

- Viewport bar chips mapped to each model's own fields (declared in `models.json`);
  a control the model does not support is shown greyed out. Raw options stay under "Advanced".
  - Image: format, aspect ratio, quality (Low/Medium/High), resolution, count.
  - 3D: mode (preview / full), model type (standard / low-poly / smart topology),
    topology (tris / quads), face count, PBR, texture resolution.
  - Video: duration, ratio, resolution, audio.
- Animation tab (v0.7.0): 678 Meshy presets (rigging + animation library on fal.ai,
  the rig is redone per preset), free text → motion (`fal-ai/hunyuan-motion`)
  retargeted onto the character's rig, and a free motion copy between two rigs.
- Retexture through `fal-ai/meshy/retexture` (v0.8.0): no Meshy key needed any more.

## Phase 3: our own local MCP server (v0.9.0)

- Built-in MCP server (`mcpserver/`, HTTP on 127.0.0.1, a port per Blender, token): compact
  typed tools (scene summary, object info, primitives, edits, materials, screenshot, generation
  that waits for its result, Poly Haven, animation presets, tasks, Python as a last resort).
- Opt-in, `mcp-for-blender` stays the default: three modes (mcp-for-blender / both / built-in
  only). Token usage shown under the chat to compare them.
- Later: Sketchfab / Poly Pizza assets, a viewport `look` with annotations, if the modes show
  they are missed.

## Phase 4: other providers with an API key

- Agent loop inside the plugin (`agent.py`) on the Phase 3 tools, through one
  OpenAI-compatible Chat Completions adapter (`providers/openai_compat.py`).
- **OpenAI** (live model list, `reasoning_effort` from the effort, token usage).
- **Gemini** on its OpenAI-compatible endpoint (thought signatures kept in the history).
- **DeepSeek** (reasoning_content sent back, its effort scale, text only, fallback model list).
- Next, presets of the same adapter: OpenRouter and a local server (Ollama).
- Released as one version when the phase is done.
