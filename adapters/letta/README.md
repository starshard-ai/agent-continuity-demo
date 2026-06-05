# FCP ↔ Letta adapter (DRAFT)

A **draft** adapter that makes this repo's cross-agent interface — the
[Fleet Coordination Protocol (FCP)](https://github.com/starshard-ai/fleet-coordination-protocol)
— speak to [Letta](https://github.com/letta-ai/letta)'s (formerly MemGPT) memory
layer.

**Status: DRAFT, not submitted anywhere.** No PR, no issue, no contact with the
Letta project. See [`PROPOSED_PR.md`](PROPOSED_PR.md) for the framing that would
accompany a future external step (owner-gated).

## Anti-absorption by design

This adapter lives **in our repo, outside Letta's boundary** — a line others can
connect to, not a primitive merged into Letta's core. FCP stays a coordination
layer *above* runtimes; Letta is one such runtime.

## What it maps

- Confident FCP facts → Letta **core memory blocks** (`fcp::<key>`, always in
  context).
- Low-confidence FCP facts → Letta **archival passages** (searchable long tail).
- FCP belief-conflict quarantine → an archival passage only; the held core block
  is never silently overwritten.

## Run the conformance test

```bash
python3 test_fcp_letta_conformance.py
```

Zero third-party deps — drives the adapter against an in-process fake Letta
client. The real `letta-client` is an optional dependency for live use.
