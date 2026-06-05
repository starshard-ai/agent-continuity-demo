#!/usr/bin/env python3
"""
Conformance test for the FCP <-> Letta adapter (DRAFT).

Zero third-party deps: drives the adapter against an in-process FakeLettaClient
that mimics the real Letta SDK surface the adapter touches, verified by
introspection against letta-client==1.12.1:
(client.agents.blocks.update / .list, client.agents.passages.create).

Proves:
  1. A confident (hot) FCP fact lands in a Letta CORE BLOCK, namespaced fcp::.
  2. A low-confidence (cold) FCP fact lands in an ARCHIVAL PASSAGE, not a block.
  3. A block round-trips back to a partial FCP fact (cross-runtime read-back).
  4. An FCP belief-conflict quarantine signal is surfaced as a passage and is
     NEVER written as a trusted core block (quarantine stays quarantined).

Run:  python3 test_fcp_letta_conformance.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fcp_letta_adapter import (  # noqa: E402
    LettaFCPAdapter, fcp_fact, fcp_block_label,
)


# ---- Fake Letta client (mimics only the surface the adapter uses) ----------

class _Block:
    def __init__(self, label, value):
        self.label = label
        self.value = value


class _Blocks:
    def __init__(self):
        self._by_agent = {}  # agent_id -> {label: _Block}

    def update(self, agent_id, block_label, value):
        self._by_agent.setdefault(agent_id, {})[block_label] = _Block(block_label, value)

    def list(self, agent_id):
        return list(self._by_agent.get(agent_id, {}).values())


class _Passages:
    def __init__(self):
        self.created = []  # list of (agent_id, text)

    def create(self, agent_id, text):
        self.created.append((agent_id, text))


class _Agents:
    # Mirrors letta-client==1.12.1: passages are agent-scoped under
    # client.agents.passages.create(agent_id, *, text) — NOT archives.passages
    # (which is archive-scoped and takes archive_id, not agent_id).
    def __init__(self, blocks, passages):
        self.blocks = blocks
        self.passages = passages


class FakeLettaClient:
    def __init__(self):
        self._blocks = _Blocks()
        self._passages = _Passages()
        self.agents = _Agents(self._blocks, self._passages)


# ---- Test helpers ----------------------------------------------------------

def _assert(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    print("ok:", msg)


def main():
    client = FakeLettaClient()
    adapter = LettaFCPAdapter(client=client, agent_id="agent-letta-1")

    # 1. hot fact -> core block
    hot = fcp_fact("project_deadline", "Friday", "agent-A",
                   belief_alpha=9.0, belief_beta=1.0,
                   created_at="2026-06-05T05:44:27Z",
                   updated_at="2026-06-05T05:44:27Z")
    r1 = adapter.push_fact(hot)
    _assert(r1["surface"] == "core_block", "hot fact -> core_block")
    label = fcp_block_label("project_deadline")
    stored = client._blocks._by_agent["agent-letta-1"][label].value
    _assert("Friday" in stored and "belief_mean=0.9" in stored,
            "core block carries value + provenance")
    _assert(label.startswith("fcp::"),
            "block label is fcp-namespaced (no collision with human/persona)")

    # 2. cold fact -> archival passage, NOT a block
    cold = fcp_fact("rumored_venue", "Hall B", "scraper",
                    belief_alpha=2.0, belief_beta=3.0,  # mean = 0.4
                    created_at="2026-06-05T05:45:00Z",
                    updated_at="2026-06-05T05:45:00Z")
    r2 = adapter.push_fact(cold)
    _assert(r2["surface"] == "archival_passage", "cold fact -> archival_passage")
    _assert(fcp_block_label("rumored_venue") not in
            client._blocks._by_agent.get("agent-letta-1", {}),
            "cold fact did NOT create a core block")
    _assert(any("rumored_venue" in t for _, t in client._passages.created),
            "cold fact text present in archival passages")

    # 3. block -> FCP fact round-trip
    facts = adapter.read_facts_from_blocks()
    rt = [f for f in facts if f["key"] == "project_deadline"]
    _assert(len(rt) == 1, "exactly one fcp fact read back from blocks")
    _assert(rt[0]["value"] == "Friday", "round-trip value preserved")
    _assert(rt[0]["source"] == "agent-A", "round-trip source preserved")
    _assert(rt[0]["belief_mean"] == 0.9, "round-trip belief_mean preserved")

    # 4. quarantine signal -> passage, never a trusted block
    blocks_before = dict(client._blocks._by_agent.get("agent-letta-1", {}))
    signal = {
        "status": "conflict_quarantined",
        "key": "project_deadline",
        "held": {"value": "Friday", "source": "agent-A"},
        "rejected": {"value": "Thursday", "source": "external-source"},
        "held_confidence": 0.8182,
    }
    r4 = adapter.push_quarantine(signal)
    _assert(r4["surface"] == "archival_passage", "quarantine -> archival_passage")
    _assert(any("conflict quarantined" in t and "Thursday" in t
                for _, t in client._passages.created),
            "rejected value surfaced in a quarantine passage")
    blocks_after = client._blocks._by_agent.get("agent-letta-1", {})
    _assert(blocks_after[fcp_block_label("project_deadline")].value
            == blocks_before[fcp_block_label("project_deadline")].value,
            "held core block UNCHANGED by quarantine (no silent overwrite)")

    print("\nALL CONFORMANCE CHECKS PASSED")


if __name__ == "__main__":
    main()
