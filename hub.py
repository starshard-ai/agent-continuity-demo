#!/usr/bin/env python3
"""
Local shared memory hub (stdlib-only).

A minimal, faithful slice of the multi-agent coordination system's memory hub:
a SQLite-backed REST API over Python's stdlib http.server. Multiple separate
agent processes talk to ONE hub over HTTP, so a fact written by one agent is
visible to any other agent — even after the first agent's process is gone.

Each fact carries a Bayesian belief (alpha, beta). Confirming evidence bumps
alpha; disconfirming evidence bumps beta. belief_mean = alpha / (alpha + beta).
This is the same alpha/beta divergence primitive the production hub uses, and
it is what lets the hub DETECT a conflicting external write instead of silently
overwriting it: a write that disagrees with a held high-confidence fact is
quarantined and flagged rather than clobbering the original.

No third-party dependencies. Runs on stock Python 3.10+ (ubuntu:22.04).
"""

import json
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Belief primitive (Bayesian alpha/beta), faithful to the production hub.
# ---------------------------------------------------------------------------

def belief_mean(alpha, beta):
    total = alpha + beta
    return (alpha / total) if total > 0 else 0.0


# A conflicting write is quarantined (not silently applied) when the current
# fact is held with high confidence AND the incoming value disagrees.
CONFLICT_CONFIDENCE_THRESHOLD = 0.66


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    key          TEXT PRIMARY KEY,
                    value        TEXT NOT NULL,
                    source       TEXT NOT NULL,
                    belief_alpha REAL NOT NULL DEFAULT 1.0,
                    belief_beta  REAL NOT NULL DEFAULT 1.0,
                    created_at   TEXT NOT NULL,
                    updated_at   TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quarantine (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    key           TEXT NOT NULL,
                    held_value    TEXT NOT NULL,
                    held_source   TEXT NOT NULL,
                    rejected_value  TEXT NOT NULL,
                    rejected_source TEXT NOT NULL,
                    held_confidence REAL NOT NULL,
                    created_at    TEXT NOT NULL
                )
                """
            )

    # -- facts ---------------------------------------------------------------

    def put_fact(self, key, value, source, confidence=0.9):
        """Create or strongly-confirm a fact.

        New fact: seed alpha/beta from confidence (n=10 pseudo-counts).
        Same value re-asserted: confirming evidence -> alpha bump.
        """
        now = utc_now()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()
            if row is None:
                alpha = max(1.0, round(confidence * 10))
                beta = max(1.0, round((1.0 - confidence) * 10))
                conn.execute(
                    "INSERT INTO facts (key,value,source,belief_alpha,belief_beta,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (key, value, source, alpha, beta, now, now),
                )
                created = True
            elif row["value"] == value:
                # same claim re-asserted -> confirming evidence
                alpha = row["belief_alpha"] + max(1.0, round(confidence * 10))
                beta = row["belief_beta"]
                conn.execute(
                    "UPDATE facts SET belief_alpha=?,source=?,updated_at=? WHERE key=?",
                    (alpha, source, now, key),
                )
                created = False
            else:
                # different value via the trusted put path -> still go through
                # conflict logic so we never silently overwrite a held belief.
                return self.submit_conflicting(key, value, source)
            row = conn.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()
        return {"status": "created" if created else "confirmed", "fact": _fact_dict(row)}

    def get_fact(self, key):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()
        return _fact_dict(row) if row else None

    def list_facts(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM facts ORDER BY key").fetchall()
        return [_fact_dict(r) for r in rows]

    def submit_conflicting(self, key, value, source):
        """An external/competing write proposing a DIFFERENT value for `key`.

        If no fact exists yet -> just store it.
        If a fact exists and the value disagrees:
          - The disagreement is disconfirming evidence -> bump beta and recompute
            the held belief mean (the alpha/beta divergence primitive).
          - If the held fact is still confident (mean >= threshold), QUARANTINE
            the incoming write: record it, flag it, do NOT overwrite.
          - Only if the held belief has collapsed below threshold do we accept
            the new value (belief genuinely eroded).
        """
        now = utc_now()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()
            if row is None:
                alpha, beta = 9.0, 1.0
                conn.execute(
                    "INSERT INTO facts (key,value,source,belief_alpha,belief_beta,"
                    "created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (key, value, source, alpha, beta, now, now),
                )
                row = conn.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()
                return {"status": "created", "fact": _fact_dict(row)}

            if row["value"] == value:
                return self.put_fact(key, value, source)

            # disagreement -> disconfirming evidence against the held fact
            alpha = row["belief_alpha"]
            beta = row["belief_beta"] + 2.0
            held_mean = belief_mean(alpha, beta)
            conn.execute(
                "UPDATE facts SET belief_beta=?,updated_at=? WHERE key=?",
                (beta, now, key),
            )

            if held_mean >= CONFLICT_CONFIDENCE_THRESHOLD:
                conn.execute(
                    "INSERT INTO quarantine (key,held_value,held_source,rejected_value,"
                    "rejected_source,held_confidence,created_at) VALUES (?,?,?,?,?,?,?)",
                    (key, row["value"], row["source"], value, source,
                     round(held_mean, 4), now),
                )
                held = conn.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()
                return {
                    "status": "conflict_quarantined",
                    "key": key,
                    "held": {"value": row["value"], "source": row["source"]},
                    "rejected": {"value": value, "source": source},
                    "held_confidence": round(held_mean, 4),
                    "fact": _fact_dict(held),
                }

            # held belief collapsed -> accept the new value
            conn.execute(
                "UPDATE facts SET value=?,source=?,belief_alpha=?,belief_beta=?,updated_at=? "
                "WHERE key=?",
                (value, source, 6.0, 1.0, now, key),
            )
            row = conn.execute("SELECT * FROM facts WHERE key=?", (key,)).fetchone()
            return {"status": "accepted_after_belief_collapse", "fact": _fact_dict(row)}

    def list_quarantine(self):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM quarantine ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def _fact_dict(row):
    if row is None:
        return None
    alpha = row["belief_alpha"]
    beta = row["belief_beta"]
    return {
        "key": row["key"],
        "value": row["value"],
        "source": row["source"],
        "belief_alpha": alpha,
        "belief_beta": beta,
        "belief_mean": round(belief_mean(alpha, beta), 4),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------------
# HTTP layer (stdlib)
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, *args):  # silence default stderr access log
        pass

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        store = self.server.store
        if path == "/health":
            self._send(200, {"status": "ok", "service": "agent-continuity-hub"})
        elif path == "/facts":
            self._send(200, {"facts": store.list_facts()})
        elif path.startswith("/facts/"):
            key = path[len("/facts/"):]
            fact = store.get_fact(key)
            if fact is None:
                self._send(404, {"detail": "not found"})
            else:
                self._send(200, fact)
        elif path == "/quarantine":
            self._send(200, {"quarantine": store.list_quarantine()})
        else:
            self._send(404, {"detail": "route not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        store = self.server.store
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._send(400, {"detail": "invalid json"})
            return
        if path == "/facts":
            result = store.put_fact(
                payload["key"], payload["value"], payload.get("source", "unknown"),
                float(payload.get("confidence", 0.9)),
            )
            self._send(201, result)
        elif path == "/facts/external":
            result = store.submit_conflicting(
                payload["key"], payload["value"], payload.get("source", "external"),
            )
            self._send(200, result)
        else:
            self._send(404, {"detail": "route not found"})


class Hub(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, db_path):
        super().__init__(addr, Handler)
        self.store = Store(db_path)


def main():
    host = "127.0.0.1"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    db_path = sys.argv[2] if len(sys.argv) > 2 else "hub.db"
    server = Hub((host, port), db_path)
    print("[hub] shared memory hub listening on http://%s:%d (db=%s)" % (host, port, db_path))
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
