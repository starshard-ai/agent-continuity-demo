# Your agents can't see each other. This fixes that.

You're running more than one agent now — Claude Code, Codex, Cursor, a cron
script, a teammate's bot. They can't see each other, can't trust each other's
memory, and can't be stopped before one of them does something irreversible
behind your back. The result: stale beliefs, duplicated work, and an email that
went out before you ever saw it.

Give them **one shared memory, one permission gate, and one receipt per action**
— a thin coordination layer that runs *above* whatever runtime you already use,
so your fleet cooperates instead of colliding.

The four primitives, all checkable in this repo:

- **Shared cross-agent / cross-device memory** — one hub every agent reads and
  writes; no in-process handoff required.
- **A permission gate before irreversible actions** — content-gated, not
  act-gated: the boundary travels with the data, not the verb.
- **A receipt for every action** — an auditable record any other session can
  replay or retract.
- **Cross-session work-claims** — agents claim work so two don't redo or
  contradict each other.

> **Architecture, one layer down:** this is the cooperative governance layer
> your fleet is missing — content-gated permissions + provenance + receipts,
> *not* LLM-as-CPU scheduling. Call it an Agent-OS layer if you like, but it's a
> cooperative protocol agents opt into, not a hardware-enforced kernel. It runs
> above any runtime (Claude Code, Codex, Hermes, OpenClaw) and is interoperable
> by design.

**What it is / why it exists.** Single agents already work. The unsolved problem
is *many* agents sharing state without losing, contradicting, or clobbering each
other — and without one of them taking an irreversible action no human approved.
This repo is the smallest honest proof that the core primitives are real, not a
pitch deck. It is not a framework and it does not replace your runtime; it sits
above it.

**This repo is the reference implementation of the
[Fleet Coordination Protocol (FCP)](https://github.com/starshard-ai/fleet-coordination-protocol).**
FCP is a narrow, descriptive `v0` spec for the four record shapes below — the
wire a runtime reads and writes to participate. The shapes in that spec are
derived from the code in *this* repo. A DRAFT adapter mapping FCP onto Letta's
memory layer lives in [`adapters/letta`](adapters/letta).

---

Below is a tiny, real demonstration of two of those primitives — cross-agent
continuity and belief-conflict detection — that make a multi-agent system
behave like one coherent mind instead of a swarm of amnesiacs:

1. **Cross-agent continuity** — agent A (a process) writes a fact to a shared
   memory hub, A exits, and a *different* agent B (a separate process) reads the
   hub and already knows the fact. No direct handoff, no shared memory in-process
   — the hub is the only thing they have in common.

2. **Belief-conflict caught** — when an external source writes a value that
   *disagrees* with a held, high-confidence fact, the hub **detects and
   quarantines** the conflict instead of silently overwriting it. You get a line
   like:

   ```
   [hub] conflict quarantined: project_deadline {agent-A:Friday, external-source:Thursday} -> flagged, not silently overwritten
   ```

That's the whole demo. It is deliberately small. It is not a framework.

## Quickstart

Requires only Python 3.10+ (stdlib only — no pip installs, no network, no keys).

```bash
./demo.sh
```

Runs in about a second and prints both demonstrations. A captured reference run
is in [`expected_output.txt`](expected_output.txt). A ~7s screen recording is in
[`demo.cast`](demo.cast) (play with `asciinema play demo.cast`).

### Runs clean on ubuntu:22.04

```bash
docker run --rm -v "$PWD":/app -w /app ubuntu:22.04 \
  bash -c "apt-get update -qq && apt-get install -y -qq python3 >/dev/null && ./demo.sh"
```

## How it works

- **`hub.py`** — a SQLite-backed REST memory hub built on Python's stdlib
  `http.server`. Each fact carries a Bayesian belief `(alpha, beta)`; confirming
  evidence bumps `alpha`, disconfirming evidence bumps `beta`, and
  `belief_mean = alpha / (alpha + beta)`. A disagreeing write is *disconfirming
  evidence*: the hub recomputes the held belief and, while it stays confident,
  routes the incoming value to a quarantine table rather than clobbering the
  held fact. This alpha/beta divergence is the conflict-detection primitive.
- **`agent.py`** — a minimal agent that talks to the hub over real HTTP
  (stdlib `urllib`). Every invocation is a *separate OS process*; nothing is
  shared between agents except the hub. The PIDs printed in the output prove the
  writer and reader are different processes.
- **`demo.sh`** — starts the hub as its own process, then orchestrates
  agent A (write + exit), agent B (read), and an external conflicting write.

All data is synthetic (a made-up `project_deadline`). Nothing here is private.

## API (for the curious)

| Method | Path                | Purpose                                            |
| ------ | ------------------- | -------------------------------------------------- |
| GET    | `/health`           | liveness                                           |
| POST   | `/facts`            | trusted write (create / confirm)                   |
| GET    | `/facts`            | list all facts                                     |
| GET    | `/facts/<key>`      | read one fact (value, source, belief)              |
| POST   | `/facts/external`   | competing write — may be quarantined               |
| GET    | `/quarantine`       | list quarantined conflicting writes                |

## License

MIT — see [LICENSE](LICENSE).
