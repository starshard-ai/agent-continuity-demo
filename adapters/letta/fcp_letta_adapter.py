#!/usr/bin/env python3
"""
FCP <-> Letta adapter (DRAFT, external to Letta).

Makes the demo's cross-agent interface — the Fleet Coordination Protocol (FCP),
see https://github.com/starshard-ai/fleet-coordination-protocol — speak to
Letta's (formerly MemGPT) memory layer.

WHY THIS LIVES HERE (anti-absorption, by design)
------------------------------------------------
This adapter lives in OUR repo, OUTSIDE Letta's boundary. It is a *line others
can connect to*, NOT a primitive merged into Letta's core. FCP is a coordination
layer ABOVE single-agent runtimes; Letta is one such runtime. The adapter maps
FCP's shared-memory fact record onto Letta's two memory surfaces:

  * Letta CORE MEMORY BLOCKS  -> short, always-in-context, label/value strings
      (client.agents.blocks.update(block_label, agent_id=, value=) /
       client.agents.blocks.list(agent_id=)). Good for a small set of hot FCP
       facts a Letta agent should always see.
  * Letta ARCHIVAL PASSAGES   -> embedding-backed long-term store
      (client.agents.passages.create(agent_id, text=...)). Good for the long
       tail of FCP facts, searchable semantically.

This is DRAFT. It targets the real `letta-client` SDK surface, verified by
introspection against letta-client==1.12.1: agents.blocks.update(block_label,
*, agent_id, value), agents.blocks.list(agent_id), and
agents.passages.create(agent_id, *, text). NOTE: the agent-scoped archival
write is `agents.passages.create(agent_id=...)`, NOT
`archives.passages.create(...)` — the latter is archive-scoped and takes an
`archive_id`, not an `agent_id`. The real `letta-client` is an OPTIONAL
dependency — import is lazy so the conformance test runs with zero third-party
deps against an in-process fake client mirroring this surface.

NOT submitted anywhere. No PR, no issue, no contact with the Letta project.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# FCP record shapes (from the SPEC, which is derived from the demo's hub.py).
# We only need the shared-memory fact record + the quarantine signal here.
# ---------------------------------------------------------------------------

def fcp_fact(key: str, value: str, source: str,
             belief_alpha: float, belief_beta: float,
             created_at: str, updated_at: str) -> dict:
    """An FCP shared-memory fact record (SPEC §2)."""
    total = belief_alpha + belief_beta
    return {
        "key": key,
        "value": value,
        "source": source,
        "belief_alpha": belief_alpha,
        "belief_beta": belief_beta,
        "belief_mean": round(belief_alpha / total, 4) if total else 0.0,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def fcp_block_label(key: str) -> str:
    """Deterministic Letta core-memory block label for an FCP fact key.

    Namespaced so FCP-managed blocks never collide with a Letta agent's own
    human/persona blocks.
    """
    return "fcp::" + key


def fact_to_block_value(fact: dict) -> str:
    """Render an FCP fact as a compact human+machine readable block value.

    Letta blocks are plain strings the model reads in-context, so we keep it
    short and legible while embedding the provenance the agent needs to reason
    about trust.
    """
    return (
        f"{fact['value']}  "
        f"(fcp_key={fact['key']}; source={fact['source']}; "
        f"belief_mean={fact['belief_mean']})"
    )


def fact_to_passage_text(fact: dict) -> str:
    """Render an FCP fact as an archival passage (searchable long-term)."""
    return (
        f"[FCP fact] {fact['key']} = {fact['value']} "
        f"| source={fact['source']} | belief_mean={fact['belief_mean']} "
        f"| updated_at={fact['updated_at']}"
    )


def block_value_to_fact(label: str, value: str) -> Optional[dict]:
    """Best-effort parse a Letta block back into a partial FCP fact.

    Round-trips what fact_to_block_value wrote. Returns None if the label is not
    FCP-namespaced.
    """
    if not label.startswith("fcp::"):
        return None
    key = label[len("fcp::"):]
    head = value.split("  (", 1)[0].strip()
    parsed = {"key": key, "value": head, "source": None, "belief_mean": None}
    if "(" in value and value.rstrip().endswith(")"):
        meta = value[value.index("(") + 1: value.rindex(")")]
        for part in meta.split(";"):
            part = part.strip()
            if part.startswith("source="):
                parsed["source"] = part[len("source="):]
            elif part.startswith("belief_mean="):
                try:
                    parsed["belief_mean"] = float(part[len("belief_mean="):])
                except ValueError:
                    pass
    return parsed


# ---------------------------------------------------------------------------
# The adapter.
# ---------------------------------------------------------------------------

# How confident an FCP fact must be (belief_mean) to earn an always-in-context
# core-memory block. Below this it still lands in archival memory.
HOT_FACT_THRESHOLD = 0.66


@dataclass
class LettaFCPAdapter:
    """Bridges FCP fact records into a Letta agent's memory.

    `client` is a Letta client (real `letta_client.Letta`, or any object with the
    same .agents.blocks / .archives.passages surface — see FakeLettaClient in the
    conformance test). `agent_id` is the Letta agent whose memory we populate.
    """

    client: Any
    agent_id: str
    hot_threshold: float = HOT_FACT_THRESHOLD
    # records every (surface, fcp_key) we wrote, so a Letta agent / another FCP
    # participant can audit what this adapter pushed.
    write_log: list = field(default_factory=list)

    # -- FCP fact  -> Letta ------------------------------------------------

    def push_fact(self, fact: dict) -> dict:
        """Push one FCP fact into Letta memory.

        Hot (confident) facts -> a core-memory block (always in context).
        Cold facts            -> an archival passage (searchable long tail).
        Returns a small receipt-like dict describing what was written.
        """
        if fact.get("belief_mean", 0.0) >= self.hot_threshold:
            surface = "core_block"
            label = fcp_block_label(fact["key"])
            self.client.agents.blocks.update(
                agent_id=self.agent_id,
                block_label=label,
                value=fact_to_block_value(fact),
            )
            ref = label
        else:
            surface = "archival_passage"
            self.client.agents.passages.create(
                agent_id=self.agent_id,
                text=fact_to_passage_text(fact),
            )
            ref = "passage"
        entry = {"surface": surface, "fcp_key": fact["key"], "ref": ref}
        self.write_log.append(entry)
        return entry

    def push_quarantine(self, signal: dict) -> dict:
        """Surface an FCP belief-conflict (SPEC §5) into Letta as an archival
        passage, so the Letta agent SEES the contradiction instead of trusting a
        silently-overwritten value. We never blindly write the rejected value
        into a core block — quarantine stays quarantined."""
        text = (
            f"[FCP conflict quarantined] key={signal['key']} "
            f"held={signal['held']['value']} (source={signal['held']['source']}) "
            f"vs rejected={signal['rejected']['value']} "
            f"(source={signal['rejected']['source']}) "
            f"held_confidence={signal.get('held_confidence')}"
        )
        self.client.agents.passages.create(agent_id=self.agent_id, text=text)
        entry = {"surface": "archival_passage", "fcp_key": signal["key"],
                 "ref": "quarantine"}
        self.write_log.append(entry)
        return entry

    # -- Letta -> FCP ------------------------------------------------------

    def read_facts_from_blocks(self) -> list:
        """Read back FCP-namespaced core blocks as partial FCP facts.

        Lets another FCP participant (or the demo hub) ingest what a Letta agent
        currently believes, closing the loop both directions.
        """
        out = []
        for block in self.client.agents.blocks.list(agent_id=self.agent_id):
            label = getattr(block, "label", None) or block.get("label")
            value = getattr(block, "value", None) or block.get("value")
            fact = block_value_to_fact(label, value)
            if fact is not None:
                out.append(fact)
        return out
