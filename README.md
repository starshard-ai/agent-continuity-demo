# Two processes share a fact and catch a conflict

This repo is a deliberately small, runnable demonstration of **two** memory
primitives:

- a fact written by one process remains available to another process; and
- a conflicting write is recorded in quarantine instead of silently replacing
  a still-confident held value.

That is the full proof boundary. This demo does **not** implement or prove a
permission gate, work claims, action receipts, resource-side fencing,
`owner-stop` propagation, independent verification, or exactly-once effects.
It also does not authenticate the free-form `source` label. Those are separate
coordination and control problems.

The companion
[Fleet Coordination Protocol (FCP)](https://github.com/starshard-ai/fleet-coordination-protocol)
describes cooperative record shapes for facts, claims, receipts, and conflict
signals. Its file-backed package implements those shapes for callers that opt
in; it is not an authorization or exactly-once layer. The fact and conflict
shapes began with the runnable code in this repo. A draft mapping of these two
shapes onto Letta lives in [`adapters/letta`](adapters/letta).

---

Below is the complete demo:

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
  `http.server`. Each fact carries an `(alpha, beta)` confidence heuristic; confirming
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
| POST   | `/facts`            | primary write path (create / confirm)              |
| GET    | `/facts`            | list all facts                                     |
| GET    | `/facts/<key>`      | read one fact (value, source, belief)              |
| POST   | `/facts/external`   | competing write — may be quarantined               |
| GET    | `/quarantine`       | list quarantined conflicting writes                |

## License

MIT — see [LICENSE](LICENSE).
