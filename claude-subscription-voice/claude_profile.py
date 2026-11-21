"""Read the voice_stream connect profile (query, headers, UA) from the locally installed Claude Code.

The values are parsed out of the `claude` binary's own voice connect code, so they follow
whatever version is installed. The scan takes ~0.3 s and runs once per process.
"""
from __future__ import annotations

import functools
import mmap
import os
import re
import shutil
import subprocess
from typing import Any

URL = "wss://api.anthropic.com/api/ws/speech_to_text/voice_stream"


def _scan(path: str) -> dict[str, Any]:
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        win = None
        for m in re.finditer(rb"\[voice_stream\] Connecting to", mm):
            w = mm[max(0, m.start() - 1500): m.end() + 1200]
            if b"URLSearchParams" in w:
                win = w.decode("utf-8", "replace")
                break
        if win is None:
            raise RuntimeError("voice_stream connect code not found in the claude binary")
        q = re.search(r"new URLSearchParams\(\{(.*?)\}\)", win, re.S).group(1)
        q = re.sub(r"\.\.\.\w+&&\{[^}]*\}", "", q)  # drop feature-flag-gated params
        hdr = re.search(r"let \w+=\{(Authorization:.*?)\};", win, re.S).group(1)
        return {
            "query": dict(re.findall(r"(\w+):\"([^\"]*)\"", q)),  # static params; `language` is the caller's
            "headers": dict(re.findall(r"\"([\w-]+)\":\"([^\"]*)\"", hdr)),
            "ua_kind": re.search(rb"claude-cli/\$\{\{.*?\}\.VERSION\} \((\w+), ", mm, re.S).group(1).decode(),
            "platform": re.search(rb"case\"cli\":default:return\"(\w+)\"", mm).group(1).decode(),
        }


@functools.lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """Return {"query", "headers", "user_agent"}; headers exclude Authorization."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude CLI not found on PATH")
    prof = _scan(os.path.realpath(exe))
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5).stdout
    ver = re.match(r"(\d+\.\d+\.\d+)", out.strip())
    if not ver:
        raise RuntimeError("cannot read `claude --version`")
    return {
        "query": prof["query"],
        "headers": {**prof["headers"], "anthropic-client-platform": prof["platform"]},
        "user_agent": f"claude-cli/{ver.group(1)} ({prof['ua_kind']}, cli)",
    }
