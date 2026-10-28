---
name: feature-pr
description: Required workflow for every change to free-plugin-blender. Create a feat/<feature> branch from an up-to-date main, run the tests, open a pull request to main, and check that the PR exists and its CI passes before starting anything else. Use it for any feature, fix or chore in this repository, even a one-line change. main is protected and cannot take direct pushes.
---

# Feature branch → tests → pull request

`main` is protected: no direct push. A change only reaches `main` through a pull
request whose `lint`, `unit-tests` and `blender-tests` checks pass. Work on one
feature at a time, and do not start the next one until the PR for the current one
exists and its checks are green.

## 1. Start from an up-to-date main

```bash
git fetch origin
git status --short            # must be empty; otherwise stop and ask what to do with the changes
git switch -c feat/<feature> origin/main
```

- `<feature>` is short kebab-case: `feat/image-controls`, `feat/animation-tab`.
  Use `fix/<bug>` for a bug fix and `chore/<task>` for tooling or docs only.
- If the branch already exists, ask the user before reusing or replacing it.

## 2. Implement

- Keep the PR to one feature. If the work grows into two, finish the first one and
  open a separate branch for the second.
- Add or update tests next to the change:
  - `tests/unit/`: pure-Python logic (schemas, catalog, payloads, text field…),
    loaded through the stand-in package in `tests/unit/conftest.py` (no bpy).
  - `tests/blender/`: anything that needs bpy. Use `harness.py`, and fake every
    network call: tests must not need a key or network access.
  - `tests/gui/`: clicks and keys through Blender's real event loop (`sim.py`).
    Needed for menus, the file browser and the modal bar, which calling Python
    directly cannot exercise. Not run in CI.
- If the user-visible version changes, bump `version` in
  `free_plugin_blender/blender_manifest.toml` and the zip name in the README.

## 3. Run the tests locally: all must pass

```bash
uvx ruff@0.14.0 check .
python3 -m pytest -q
python3 scripts/run_blender_tests.py --blender ~/.local/opt/blender-5.2.2-linux-x64/blender
# when the change touches the viewport bar or any UI flow (opens a Blender window, needs a display):
python3 scripts/run_gui_tests.py --blender ~/.local/opt/blender-5.2.2-linux-x64/blender
```

Fix the code, never the expectation, unless the test itself is wrong; then say so in
the PR. Do not open the PR with a failing test.

## 4. Commit and push the branch

```bash
git add -A
git commit -m "<type>: <what changed>"   # type: feat, fix, chore, docs, test
git push -u origin feat/<feature>
```

End the commit message with the attribution lines required by the session, if any.

## 5. Open the pull request to main

```bash
gh pr create --base main --head feat/<feature> --title "<type>: <summary>" --body-file <file>
```

The body says what changed and why, how it was tested (the commands above and what
was checked by hand), and what was not tested. End it with the attribution line
required by the session, if any.

## 6. Check that the PR exists and is green before moving on

```bash
gh pr view feat/<feature> --json number,url,state,baseRefName,headRefName
gh pr checks feat/<feature> --watch --fail-fast
```

- The PR must be `OPEN`, with base `main` and head `feat/<feature>`.
- Every check must pass. If one fails, read its log (`gh run view <run-id> --log-failed`),
  fix it on the same branch, push, and watch again.
- Then report the PR URL and the check results to the user. Only then start the next
  feature, from step 1.

## Never

- Push to `main`, force-push to `main`, or change the branch protection to get a change through.
- Merge a PR the user has not asked you to merge.
- Skip a step because the change looks small.
