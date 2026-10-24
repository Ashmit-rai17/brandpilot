# BrandPilot task board

Times are IST. Building ends 16:30 (final building and submission), closing 17:50. **Code freeze 16:15.** Submission work starts 16:15 no matter what.

## Must do

| # | Task | Owner | Depends on | Acceptance | Status | Est |
| --- | --- | --- | --- | --- | --- | --- |
| M1 | Spike A: `python -m spikes.spike_a_hello` reachable in ASI:One | Raj | .env seed | Echo reply visible in ASI:One chat | DONE (agent-to-agent via mailbox; ASI:One UI check pending Raj) | 15m |
| M2 | Spike B: `python -m spikes.spike_b_image` | Raj | ASI1 key | `data/spike_b.png` opens; note latency | DONE (200, 6-8s, upload OK) | 10m |
| M3 | Spike C: `python -m spikes.spike_c_llm` | Raj | ASI1 key | source prints `asi1`, two valid style ids | DONE (asi1 for brief + directions) | 5m |
| M4 | Run `agent.py`, mailbox connect, full flow in ASI:One | Raj | M1-M3 | Poster image renders in ASI:One (resource mode) | AGENT SIDE DONE (2 clean mailbox runs; ResourceContent sent + downloadable by recipient). ASI:One render check pending Raj | 30m |
| M5 | Image visibility test in a shared chat opened from another account | Raj + Prashant | M4 | Prashant sees the poster via the shared URL | TODO | 10m |
| M6 | Fix whatever M4/M5 reveal (cards parsing, delivery) | Raj | M4 | Two clean end-to-end runs | DONE agent side (fixes e5d6f6e, c7bdaf9, 46ba897, c9d497f; verified 14:38 incl. prose click + repeated approve). ASI:One UI retest pending Raj | 45m |
| M7 | Agentverse profile: name, handle, README with example prompts, badges | Prashant | M4 | ASI:One search finds BrandPilot | TODO | 20m |
| M8 | Public GitHub repo, README address filled, no `.env` committed | Prashant | M4 | Repo opens logged out | TODO | 15m |
| M9 | Record shared-chat URL of a clean run | Raj | M6 | URL opens logged out | TODO | 10m |
| M10 | Demo video 3 to 5 min | Raj + Prashant | M9 | Uploaded, link public | TODO | 25m |
| M11 | Submit via Project Submission Agent on the dashboard | Prashant | M7-M10 | All links re-verified after submission | TODO | 10m |

## Should do

| # | Task | Owner | Depends on | Acceptance | Status | Est |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | `knowledge/references.json`: 2 verified references per style (url, name, style_id, verified_on) | Prashant | none | `python -m tests.validate_knowledge` prints OK | TODO | 40m |
| S2 | Show one reference per direction in the carousel text | Raj | S1 | Reference name and URL appear, URL opens | TODO | 15m |
| S3 | Contract tests: invalid palette hex, unknown font id, patch with extra key rejected | Prashant | none | pytest green | TODO | 30m |
| S4 | Demo checklist rehearsal with exact prompts | Prashant | M6 | Run completes in under 4 minutes | TODO | 15m |

## Cut if behind

| # | Task | Cut trigger |
| --- | --- | --- |
| C1 | Social post demo segment | Cut if M6 not done by 15:15 |
| C2 | Warmth revision in the demo | Demo vibrancy only |
| C3 | Reference evidence (S1, S2) | Cut if not merged by 15:30 |
| C4 | CSS launch kit in video | Mention verbally |

## Decisions

* State keyed by sender only (matches the official cards example); one active design session per ASI:One user.
* Image delivery default `resource` (Agentverse ExternalStorage + ResourceContent). If M5 fails, set `IMAGE_DELIVERY=url` for the recorded demo and state the limitation.
* Vibrancy uses HSV saturation (hue and value kept). Backgrounds are reused for vibrancy and spacing revisions.
* 5 styles: Dark Minimal, Warm Editorial, Neo-brutalism, Frutiger Aero, Swiss International.
* Payment Protocol, landing page, live scraping, multi-agent: out of scope.

## Demo script

Agent: `agent1qw0pqhpynjdc7hx9r0q8g9ng6yzp3cflw7wpm5kfc8j78dy9qq3qudhsf7r` (port 8010, `IMAGE_DELIVERY=resource`).
Times are agent reply latency through Agentverse mailboxes (live test client, run A, 24 Oct 14:22, no other traffic).
ASI:One UI adds its own overhead; re-time in the rehearsal (S4).

| Step | You send | Expect | Time |
| --- | --- | --- | --- |
| 1 | I'm launching Forge, an AI productivity tool for senior developers. Calm, precise, premium. Headline: Ship calmer, build faster. | Two directions carousel (Dark Minimal + one more), one ruled-out style | 9.7s |
| 2 | Click **Choose** on Dark Minimal (or reply `1`) | Design system review card, contrast 17.6:1 | 7.1s |
| 3 | Click **Approve and make poster** | Poster v1 image + design check 5/5 | 16.9s |
| 4 | make the colors more vibrant | Review card: primary, accent, vibrancy changed; typography preserved | 7.6s |
| 5 | Click **Approve and regenerate** | Poster v2, same background recolored, 5/5 | 11.7s |
| 6 | done | CSS launch kit, session ends | 6.3s |
| reset | restart | Fresh brief form | 5.2s |

Total agent time about 64s. A second run (run B) took 1.1 to 2.6x longer per step while another ASI:One user was chatting with the agent.
