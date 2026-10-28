# Tokens per MCP mode (Scene chat)

Measured on 2026-10-28 with the real Claude Code 2.1.312 on a Claude subscription,
`scripts/bench_mcp_modes.py`: a fresh throwaway Blender 5.2.2 per run (default scene),
mcp-for-blender on port 9877, one chat turn per run, default effort. **One run per cell**:
the numbers move from run to run, read them as orders of magnitude.

Modes: `EXTERNAL` = mcp-for-blender (the default), `BOTH` = both tool sets,
`OWN` = the built-in Free Plugin tools only.

Tasks (`scripts/bench/driver.py`):
- **build**: a wooden table with four chairs, a floor and a warm sun.
- **batch**: a 5 × 5 grid of cubes, one material each, red to blue.
- **look**: critique the camera view in two sentences, change nothing.

"Tokens in" counts everything sent over the turn (each model call re-sends the context);
"cached" is the part read from the prompt cache. "Cost" is the API price Claude Code
reports, a proxy for subscription usage.

## Opus 5.5 (the chat's default model)

| Task | Mode | Done | Turns | Tool calls | Tokens in (cached) | Tokens out | Cost (API $) | Time |
|---|---|---|---|---|---|---|---|---|
| build | EXTERNAL | yes | 5 | 4 | 50,077 (42,755) | 2,944 | 0.126 | 31 s |
| build | BOTH | yes | 5 | 4 | 76,135 (69,024) | 2,399 | 0.119 | 27 s |
| build | OWN | yes | 4 | 3 | 29,021 (20,179) | 2,407 | 0.123 | 38 s |
| batch | EXTERNAL | yes | 7 | 6 | 75,966 (68,382) | 1,576 | 0.106 | 22 s |
| batch | BOTH | yes | 3 | 2 | 42,867 (37,593) | 908 | 0.068 | 13 s |
| batch | OWN | yes | 4 | 3 | 26,286 (24,141) | 981 | 0.042 | 16 s |
| look | EXTERNAL | yes | 4 | 3 | 35,079 (29,854) | 655 | 0.061 | 14 s |
| look | BOTH | yes | 3 | 2 | 28,549 (23,200) | 432 | 0.056 | 8 s |
| look | OWN | yes | 3 | 2 | 12,888 (11,111) | 272 | 0.022 | 6 s |

## Haiku 5.5

| Task | Mode | Done | Turns | Tool calls | Tokens in (cached) | Tokens out | Cost (API $) | Time |
|---|---|---|---|---|---|---|---|---|
| build | EXTERNAL | yes | 5 | 4 | 57,655 (48,391) | 3,326 | 0.004 | 21 s |
| build | BOTH | yes | 8 | 7 | 124,880 (104,280) | 4,073 | 0.007 | 25 s |
| build | OWN | yes | 42 | 41 | 115,878 (95,417) | 11,624 | 0.011 | 54 s |
| batch | EXTERNAL | yes | 6 | 5 | 82,871 (73,636) | 2,265 | 0.004 | 16 s |
| batch | BOTH | yes | 4 | 3 | 61,943 (54,878) | 1,597 | 0.003 | 13 s |
| batch | OWN | yes | 28 | 27 | 44,062 (34,611) | 5,816 | 0.005 | 24 s |
| look | EXTERNAL | yes | 3 | 2 | 25,306 (19,279) | 757 | 0.002 | 6 s |
| look | BOTH | yes | 3 | 2 | 30,359 (24,029) | 658 | 0.002 | 7 s |
| look | OWN | yes | 3 | 2 | 14,633 (12,745) | 452 | 0.001 | 5 s |

## What it shows

- **Every model call re-sends the whole context** (system prompt + tool definitions +
  history). Turns are what cost: about 5k tokens per call with the built-in tools,
  8–12k with mcp-for-blender, more with both.
- **With Opus, `OWN` is already the cheapest**: it writes one `run_python` script for the
  whole scene (3–4 turns) and sends about 2× fewer tokens than `EXTERNAL`.
  `BOTH` pays for both sets of tool definitions and never wins.
- **Haiku does not batch**: in `OWN` it called `add_object` 31 times for the dining set
  (42 turns, 4× the output tokens). The round trips the code-mode idea targets are real,
  but they depend on the model.
- mcp-for-blender's `execute_blender_code` already works like a script: few turns,
  but a heavier context per turn.

## Next

- A `run_script` tool: a script that calls the Free Plugin tools themselves
  (generation, assets, waiting for a task) so multi-step flows take one call.
  Measure it with a Poly Haven task added to this benchmark (free, several steps).
- Tell the model, in the `OWN` prompt, to group many objects in one script.
