# BrandPilot

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

BrandPilot is an AI brand and design director for founders without design expertise. Inside one ASI:One conversation it turns a brief into two evidence-based visual directions, locks a structured design system, generates a poster whose typography is rendered in code rather than by the image model, checks the result against measurable design rules, and applies controlled revisions that change only what you asked for.

**Problem:** founders can't choose a visual direction, and AI image tools drift style on every prompt.
**Users:** pre-launch startup founders.
**Outcome:** an approved, versioned design system plus launch assets that obey it, and copy-ready CSS variables.

## Agents

| Name | Address | Agentverse profile |
| --- | --- | --- |
| BrandPilot | `agent1q...` (fill in after first run) | link after registration |

Protocol: Agent Chat Protocol (ACP) with `publish_manifest=True`, mailbox agent, ASI:One Interactive Cards (form, carousel, review).

## How it works

1. **Brief.** ASI1 extracts company, product, audience, industry, positioning, personality and headline. A form card asks only for what's missing.
2. **Directions.** Code filters the 5-style catalogue (`knowledge/styles.json`) by each style's `avoid_when` tags; ASI1 picks two of the surviving styles and justifies them. One ruled-out style is shown with its reason.
3. **Design system.** The chosen style becomes a validated, versioned `DesignSystem` (palette roles, fonts, type scale, spacing, imagery, negatives, locks). Text contrast is computed before approval.
4. **Poster.** A deterministic prompt template asks ASI1 image generation for a text-free background. Pillow renders the headline, product line and brand mark with the locked font files.
5. **Design check.** Measured on the rendered pixels and actual font sizes: headline and body contrast (worst case under the text), margin, type scale, font family count.
6. **Revision.** ASI1 turns a request into a structured `Patch` restricted to an allowlist (vibrancy, warmth, spacing, image style). Code applies it, refuses locked properties (typography), shows changed vs preserved properties, and only saves v2 after approval. Vibrancy and spacing revisions reuse the same background so composition is preserved.
7. **Extras.** `social post` makes a matching square post; `done` returns the launch kit as CSS variables.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill ASI1_API_KEY, AGENT_SEED, AGENTVERSE_API_KEY
python -m pytest -q           # offline end-to-end tests
python simulate.py --offline  # full flow in the terminal, no API calls
python -m spikes.spike_c_llm   # gate: ASI1 chat JSON (prints source: asi1)
python -m spikes.spike_b_image # gate: ASI1 image -> data/spike_b.png (add --upload for Agentverse storage)
python -m spikes.spike_a_hello # gate: echo agent reachable from ASI:One
python agent.py               # open the inspector URL in the logs -> Connect -> Mailbox
```

Spikes also run as plain scripts from the project root, e.g. `python spikes/spike_c_llm.py`.

Then on agentverse.ai open the agent, fill in its README and handle, and click **Chat with Agent**. Example prompts:

* "I'm launching Forge, an AI productivity tool for senior developers. Calm, precise, premium. Headline: Ship calmer, build faster."
* "Make the colors more vibrant" (then approve)
* "Social post" / "done"

## Extra resources

ASI:One API key (asi1.ai), Agentverse account and API key. Fonts are bundled in `assets/fonts` (Google Fonts, SIL Open Font License).

## Repository layout

| Path | Owner | Purpose |
| --- | --- | --- |
| `agent.py` | Raj | uAgent, ACP, cards and image delivery |
| `brandpilot/flow.py` | Raj | state machine BRIEF, DIRECTIONS, REVIEW_DS, ASSETS, REVISE_CONFIRM, DONE |
| `brandpilot/brain.py`, `asi1.py` | Raj | ASI1 calls, validation, fallbacks |
| `brandpilot/render.py`, `revise.py` | Raj | typography, checks, controlled revisions |
| `brandpilot/models.py` | frozen | data contracts |
| `knowledge/*.json`, `assets/fonts` | Prashant | style and typography catalogues |
| `tests/` | Prashant (+ Raj for e2e) | contract and workflow tests |

## Known limits

Image generation quality depends on ASI1's image model. Checks measure the poster as rendered; they do not judge aesthetics. Image delivery uses Agentverse storage permissioned to the chatting user; see TASKBOARD.md for the shared-chat visibility test.
