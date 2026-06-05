# Proposed PR (DRAFT — owner review required, NOT submitted)

> This is a draft description for a potential future pull request. **Nothing has
> been submitted to the Letta project.** No PR, no issue, no contact. This file
> exists so the owner can review the framing before any external step.

## Where it would go

**Into THIS repo** (`starshard-ai/agent-continuity-demo`, the FCP reference
implementation) — NOT into `letta-ai/letta`.

This is the anti-absorption constraint, stated plainly: the adapter is a line
that connects *to* Letta from outside its boundary. It is not a feature merged
into Letta's core. If Letta later wants to reference it, great — but FCP must
stay a coordination layer **above** runtimes, not a primitive **inside** one.

## Title

`adapters/letta: DRAFT FCP <-> Letta memory adapter + conformance test`

## What it does

Makes the demo's cross-agent interface — the
[Fleet Coordination Protocol (FCP)](https://github.com/starshard-ai/fleet-coordination-protocol)
— speak to Letta's (formerly MemGPT) memory layer, the runtime whose memory
model is closest to our shared hub.

Mapping (FCP fact record, SPEC §2 → Letta):

SDK calls verified by introspection against `letta-client==1.12.1` (see Caveats):

| FCP fact | Letta surface | Letta SDK call |
| --- | --- | --- |
| confident fact (`belief_mean >= 0.66`) | core memory block, label `fcp::<key>` | `client.agents.blocks.update(block_label, agent_id=, value=)` |
| low-confidence fact | archival passage | `client.agents.passages.create(agent_id, text=...)` |
| belief-conflict quarantine (SPEC §5) | archival passage only | `client.agents.passages.create(agent_id, text=...)` |
| read-back | partial FCP facts | `client.agents.blocks.list(agent_id)` |

Key design choices:

- **Namespaced blocks** (`fcp::<key>`) so FCP-managed memory never collides with
  a Letta agent's own `human` / `persona` blocks.
- **Quarantine stays quarantined**: an FCP conflict signal is surfaced as a
  passage the Letta agent can *see and reason about*, and is **never** written
  into a trusted core block. The held belief's block is left untouched — no
  silent overwrite crosses the runtime boundary. (Conformance-tested.)
- **Optional dependency**: `letta-client` import is lazy. The conformance test
  runs with zero third-party deps against an in-process fake client mirroring
  the SDK surface.

## Test

`adapters/letta/test_fcp_letta_conformance.py` — 13 assertions, stdlib-only,
passes. Proves hot→block, cold→passage, block→fact round-trip, and the
quarantine-no-overwrite invariant.

## Caveats for review

- **SDK surface verified** by introspecting `letta-client==1.12.1` (the current
  client SDK) — not just documented. All four method paths exist and their
  signatures `bind()` cleanly against the exact kwargs the adapter passes:
  `agents.blocks.update(block_label, *, agent_id, value)`,
  `agents.blocks.list(agent_id)`, `agents.passages.create(agent_id, *, text)`.
- **One real mismatch was caught and fixed during this smoke**: the draft
  originally called `archives.passages.create(agent_id=, text=)`. In the real
  SDK `archives.passages.create` is **archive-scoped** and requires
  `archive_id`, not `agent_id` (it raises `TypeError: missing a required
  argument: 'archive_id'`). The agent-scoped archival write is
  `client.agents.passages.create(agent_id=, text=)`, which is what the adapter
  now uses. This is exactly the class of drift the smoke was meant to find
  (cf. the earlier `.modify` → `.update` rename).
- Verification was **method-surface only** (import + `inspect`/`bind`); no live
  Letta server or API key was used, so the calls have not been exercised
  end-to-end against a running agent. The conformance test still runs against an
  in-process fake mirroring this verified surface.
- This is `v0` and tracks FCP `v0` — both are explicitly unstable.
