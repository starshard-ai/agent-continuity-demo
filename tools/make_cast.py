#!/usr/bin/env python3
"""
Build an asciinema v2 .cast from captured demo output, with volatile bits
(temp db path, PIDs) normalized so the recording is reproducible and clean.

This does NOT require the asciinema binary; it emits the documented
asciicast v2 JSON-lines format directly, playable by `asciinema play demo.cast`
or the asciinema web player. Usage: make_cast.py <input.txt> <out.cast>
"""
import json
import re
import sys

src = open(sys.argv[1], encoding="utf-8").read()

# normalize volatile content
src = re.sub(r"db=\S+hub\.db", "db=/tmp/hub.db", src)
src = re.sub(r"pid=\d+", "pid=<pid>", src)

lines = src.splitlines()

header = {
    "version": 2,
    "width": 90,
    "height": 32,
    "timestamp": 0,
    "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
    "title": "agent-continuity-demo",
}

out = [json.dumps(header)]
t = 0.0
# prompt + command at t=0
out.append(json.dumps([t, "o", "$ ./demo.sh\r\n"]))
for ln in lines:
    t += 0.18  # ~0.18s per line -> ~7s for ~39 lines; well under 60s
    out.append(json.dumps([round(t, 3), "o", ln + "\r\n"]))
t += 0.4
out.append(json.dumps([round(t, 3), "o", "$ \r\n"]))

with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")

print("wrote %s (%d events, ~%.1fs)" % (sys.argv[2], len(out) - 1, t))
