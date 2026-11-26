"""Connect profile (query, headers, UA) for voice_stream, following the locally installed Claude Code.

On load the values are parsed out of the `claude` binary's own voice connect code (~0.3 s, once per
process). Built-in DEFAULTS are the fallback: if parsing fails the plugin keeps working with them, and a
mismatch between parsed values and DEFAULTS is logged once as a hint that Claude Code changed.
"""
from __future__ import annotations

import functools
import json
import logging
import mmap
import os
import re
import shutil
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)

URL = "wss://api.anthropic.com/api/ws/speech_to_text/voice_stream"

# Values observed in Claude Code 2.1.330 (terminal entrypoint). `language` is supplied by the caller.
DEFAULTS: dict[str, Any] = {
    "query": {"encoding": "linear16", "sample_rate": "16000", "channels": "1", "endpointing_ms": "300",
              "utterance_end_ms": "1000", "use_conversation_engine": "true"},
    "headers": {"x-app": "cli"},
    "platform": "claude_code_cli",
    "ua_kind": "external",
}


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


def _version(exe: str) -> str:
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5).stdout
    m = re.match(r"(\d+\.\d+\.\d+)", out.strip())
    if not m:
        raise RuntimeError("cannot read `claude --version`")
    return m.group(1)


@functools.lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    """Return {"query", "headers", "user_agent"}; headers exclude Authorization, user_agent may be None."""
    prof, version = dict(DEFAULTS), None
    exe = shutil.which("claude")
    if exe:
        try:
            scanned = _scan(os.path.realpath(exe))
            if scanned != {k: DEFAULTS[k] for k in scanned}:
                logger.warning("claude-subscription-voice: Claude Code's voice_stream profile differs from "
                               "the built-in defaults (Claude Code changed?): %s", scanned)
            prof = {**DEFAULTS, **scanned}
        except Exception as exc:
            logger.warning("claude-subscription-voice: could not parse Claude Code, using defaults: %s", exc)
        try:
            version = _version(exe)
        except Exception as exc:
            logger.warning("claude-subscription-voice: %s; User-Agent will be omitted", exc)
    else:
        logger.warning("claude-subscription-voice: claude CLI not found on PATH; using defaults")
    return {
        "query": prof["query"],
        "headers": {**prof["headers"], "anthropic-client-platform": prof["platform"]},
        "user_agent": f"claude-cli/{version} ({prof['ua_kind']}, cli)" if version else None,
    }


CREDENTIALS_FILE = os.path.expanduser("~/.claude/.credentials.json")  # where Claude Code keeps its login off macOS


def has_login_store() -> bool:
    """True when this machine has a place Claude Code keeps its login (Keychain on macOS, a file elsewhere)."""
    return bool(shutil.which("security")) or os.path.isfile(CREDENTIALS_FILE)


def token() -> str:
    """Claude Code's OAuth access token. Inside Hermes, Hermes' own resolver reads it and refreshes it when expired."""
    try:
        # Refresh tokens are single-use: only Hermes' resolver (shared lock, Keychain mirror) may spend one.
        # shortcut: private Hermes helper; if it is renamed we fall back to the read-only path below.
        from agent.anthropic_credentials import _resolve_claude_code_token_from_credentials as resolve
    except ImportError:  # outside Hermes (scripts/probe.py) or an older Hermes
        return _read_token()
    tok = resolve()
    if not tok:
        raise RuntimeError("Claude Code login missing, or expired and Hermes could not refresh it "
                           "(run `claude auth login`)")
    return tok


def _read_token() -> str:
    """Read-only: macOS Keychain item, else ~/.claude/.credentials.json (same JSON shape)."""
    if shutil.which("security"):
        out = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            raise RuntimeError("Claude Code login not found in Keychain (run `claude auth login`)")
        raw = out.stdout
    else:
        try:
            with open(CREDENTIALS_FILE, encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            raise RuntimeError(f"Claude Code login not found at {CREDENTIALS_FILE} (run `claude auth login`)") from None
    oauth = json.loads(raw)["claudeAiOauth"]
    if oauth.get("expiresAt", 0) / 1000 < time.time() + 30:
        raise RuntimeError("Claude Code token expired — run `claude` once to refresh it")
    return oauth["accessToken"]


def headers() -> dict[str, str]:
    """All connect headers: Authorization, User-Agent (when known) and the profile's static headers."""
    prof = load()
    ua = {"User-Agent": prof["user_agent"]} if prof["user_agent"] else {}
    return {"Authorization": f"Bearer {token()}", **ua, **prof["headers"]}
