#!/usr/bin/env python3
"""
A minimal agent process. Talks to the shared memory hub over real HTTP
(stdlib urllib only). Each invocation is a SEPARATE OS process; the only thing
shared between them is the hub. State lives in the hub, never in the process.

Usage:
  agent.py <hub_url> <agent_name> write    <key> <value> [confidence]
  agent.py <hub_url> <agent_name> read     <key>
  agent.py <hub_url> <agent_name> external <key> <value>   # competing write
"""

import json
import sys
import urllib.request


def _request(url, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    hub = sys.argv[1].rstrip("/")
    name = sys.argv[2]
    action = sys.argv[3]
    pid = __import__("os").getpid()

    if action == "write":
        key, value = sys.argv[4], sys.argv[5]
        confidence = float(sys.argv[6]) if len(sys.argv) > 6 else 0.9
        result = _request(
            hub + "/facts", "POST",
            {"key": key, "value": value, "source": name, "confidence": confidence},
        )
        print("[%s pid=%d] wrote fact to hub: %s = %r (belief_mean=%.2f)"
              % (name, pid, key, value, result["fact"]["belief_mean"]))

    elif action == "read":
        key = sys.argv[4]
        try:
            fact = _request(hub + "/facts/" + key)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print("[%s pid=%d] hub has NO fact for %r" % (name, pid, key))
                sys.exit(2)
            raise
        print("[%s pid=%d] read fact from hub (written by a DIFFERENT process): "
              "%s = %r" % (name, pid, fact["key"], fact["value"]))
        print("           -> source recorded in hub: %s | belief_mean=%.2f"
              % (fact["source"], fact["belief_mean"]))

    elif action == "external":
        key, value = sys.argv[4], sys.argv[5]
        result = _request(
            hub + "/facts/external", "POST",
            {"key": key, "value": value, "source": name},
        )
        if result["status"] == "conflict_quarantined":
            print("[%s pid=%d] proposed %s = %r" % (name, pid, key, value))
            print("[hub] conflict quarantined: %s {%s:%s, %s:%s} -> flagged, "
                  "not silently overwritten (held_confidence=%.2f)"
                  % (key,
                     result["held"]["source"], result["held"]["value"],
                     result["rejected"]["source"], result["rejected"]["value"],
                     result["held_confidence"]))
        else:
            print("[%s pid=%d] external write status=%s" % (name, pid, result["status"]))

    else:
        print("unknown action: %s" % action, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
