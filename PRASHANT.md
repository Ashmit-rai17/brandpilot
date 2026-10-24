# Prashant: your tasks

You never edit files under `brandpilot/` or `agent.py`. Your files: `knowledge/`, `assets/fonts/`, `tests/` (except `test_e2e_flow.py`), `README.md`, `TASKBOARD.md`.

Setup: `pip install -r requirements.txt`, then `python -m pytest -q` should print `10 passed`.

## Task 1: references.json (40 min)

Create `knowledge/references.json`:

```json
{"references": [
  {"id": "linear", "name": "Linear", "url": "https://linear.app", "style_id": "dark_minimal",
   "why": "near-black UI, single indigo accent, neutral sans", "verified_on": "2026-10-24"}
]}
```

Rules: 2 per style, `style_id` must be one of `dark_minimal, editorial, neo_brutalism, frutiger_aero, swiss`. Open every URL yourself in a browser; only add it if it loads and actually looks like that style. Never guess.
Done when `python -m tests.validate_knowledge` prints `OK`.

## Task 2: contract tests (30 min)

In `tests/test_contracts.py` write pytest tests that check: a `Palette` with `"#12345"` raises `ValidationError`; `Patch(saturation="neon")` raises; every style's fonts exist (already in test_rules, extend for references); `apply_patch` with `Patch(wants_font_change=True)` raises `RevisionRejected`.
Done when `python -m pytest -q` is green.

## Task 3: Agentverse profile and repo (after Raj's agent runs)

Fill the README table with the address Raj gives you. Paste the README into the Agentverse profile (Edit), set handle `brandpilot`, add the two badges. Make the GitHub repo public, check `.env` is not in it.

## Task 4: demo checklist

Write the exact prompts for the video in TASKBOARD.md and time one rehearsal.
