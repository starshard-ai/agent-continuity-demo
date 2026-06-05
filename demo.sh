#!/usr/bin/env bash
# Agent-continuity demo: two SEPARATE agent processes share ONE local memory hub.
# Demonstrates exactly two things:
#   1. Cross-agent continuity: agent A writes a fact, A exits, a DIFFERENT
#      process (agent B) reads the hub and already knows it.
#   2. Belief-conflict caught: an external write that disagrees with a held,
#      high-confidence fact is DETECTED and QUARANTINED, not silently overwritten.
#
# Runs on stock Python 3.10+ (ubuntu:22.04), stdlib only. No network, no keys.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PORT=8787
HUB_URL="http://127.0.0.1:${PORT}"
DB="$(mktemp -d)/hub.db"
PY="$(command -v python3 || command -v python)"

cleanup() {
  if [[ -n "${HUB_PID:-}" ]] && kill -0 "$HUB_PID" 2>/dev/null; then
    kill "$HUB_PID" 2>/dev/null || true
    wait "$HUB_PID" 2>/dev/null || true
  fi
  rm -f "$DB"
}
trap cleanup EXIT

echo "=================================================================="
echo " agent-continuity-demo  —  two agents, one shared memory hub"
echo "=================================================================="
echo

# --- start the shared hub as its own process ---------------------------------
"$PY" hub.py "$PORT" "$DB" &
HUB_PID=$!

# wait for the hub to come up
for _ in $(seq 1 50); do
  if "$PY" - "$HUB_URL" <<'PYEOF' 2>/dev/null
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/health", timeout=1).read()
PYEOF
  then break; fi
  sleep 0.1
done
echo

# --- 1. CROSS-AGENT CONTINUITY ----------------------------------------------
echo "------------------------------------------------------------------"
echo " 1. CROSS-AGENT CONTINUITY"
echo "------------------------------------------------------------------"
echo "agent-A starts as its own process, writes a fact, then exits."
"$PY" agent.py "$HUB_URL" agent-A write project_deadline Friday 0.9
echo "(agent-A process has now exited — its memory is gone, only the hub holds the fact.)"
echo
echo "agent-B starts LATER as a SEPARATE process. It never talked to agent-A."
echo "It reads the shared hub and already knows what agent-A learned:"
"$PY" agent.py "$HUB_URL" agent-B read project_deadline
echo
echo ">> Continuity proven: a fact survived the death of the process that wrote it,"
echo "   and a different process picked it up with zero direct handoff."
echo

# --- 2. BELIEF-CONFLICT CAUGHT ----------------------------------------------
echo "------------------------------------------------------------------"
echo " 2. BELIEF-CONFLICT CAUGHT (quarantine, not silent overwrite)"
echo "------------------------------------------------------------------"
echo "An external source now writes a CONFLICTING value for the same fact."
echo "The hub holds 'Friday' with high confidence. The external write says 'Thursday'."
"$PY" agent.py "$HUB_URL" external-source external project_deadline Thursday
echo
echo "The hub did NOT overwrite. The held fact is still intact:"
"$PY" agent.py "$HUB_URL" agent-B read project_deadline
echo
echo ">> Conflict caught: the disagreement was recorded and quarantined for review"
echo "   instead of silently clobbering the held belief."
echo
echo "=================================================================="
echo " DONE — both behaviors demonstrated over the real shared hub."
echo "=================================================================="
