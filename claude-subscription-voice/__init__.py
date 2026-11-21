"""claude-subscription-voice: Hermes STT provider backed by Claude's voice_stream (Deepgram Nova 3).

Reads the Claude Code OAuth access token from the macOS Keychain (read-only; Claude Code
owns refresh). Sends the same headers/query as Claude Code; only the UA version is read from the local install.
"""
from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from typing import Any, Optional

from agent.transcription_provider import TranscriptionProvider, TranscriptionStreamSession

NAME = "claude-subscription-voice"
URL = "wss://api.anthropic.com/api/ws/speech_to_text/voice_stream"
LANGS = {"en", "es", "fr", "ja", "de", "pt", "it", "ko", "hi", "id", "ru", "pl", "tr", "nl", "uk", "el",
         "cs", "da", "sv", "no"}
CHUNK = 3200  # 100 ms of 16 kHz s16le mono


def _token() -> str:
    out = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                         capture_output=True, text=True, timeout=5)
    if out.returncode != 0:
        raise RuntimeError("Claude Code login not found in Keychain (run `claude auth login`)")
    oauth = json.loads(out.stdout)["claudeAiOauth"]
    if oauth.get("expiresAt", 0) / 1000 < time.time() + 30:
        raise RuntimeError("Claude Code token expired — run `claude` once to refresh it")
    return oauth["accessToken"]


@functools.lru_cache(maxsize=1)
def _version() -> str:
    """Version of the locally installed Claude Code (the only part of the headers that changes)."""
    out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5).stdout
    m = re.match(r"(\d+\.\d+\.\d+)", out.strip())
    if not m:
        raise RuntimeError("cannot read `claude --version`")
    return m.group(1)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "User-Agent": f"claude-cli/{_version()} (external, cli)",
            "x-app": "cli", "anthropic-client-platform": "claude_code_cli"}


def _lang(language: Optional[str]) -> str:
    base = (language or "ko").lower().split("-")[0]
    return base if base in LANGS else "ko"


class _Stream(TranscriptionStreamSession):
    """One utterance over one voice_stream socket."""

    def __init__(self, language: Optional[str]):
        from websockets.sync.client import connect
        query = urllib.parse.urlencode(dict(
            encoding="linear16", sample_rate=16000, channels=1, endpointing_ms=300, utterance_end_ms=1000,
            language=_lang(language), use_conversation_engine="true"))
        self._ws = connect(f"{URL}?{query}", open_timeout=10,
                           additional_headers=_headers())
        self._lock = threading.Lock()
        self._segments: list[str] = []
        self._current = ""
        self._error = ""
        self._closed = threading.Event()
        self._ws.send('{"type":"KeepAlive"}')
        threading.Thread(target=self._recv, daemon=True).start()
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _recv(self) -> None:
        try:
            for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                msg = json.loads(raw)
                kind = msg.get("type")
                with self._lock:
                    if kind in ("TranscriptText", "TranscriptInterim"):
                        self._current = msg.get("data", "")
                    elif kind == "TranscriptEndpoint":
                        if self._current:
                            self._segments.append(self._current)
                        self._current = ""
                    elif kind in ("TranscriptError", "error"):
                        self._error = str(msg.get("message") or msg.get("description") or msg)
        except Exception as exc:  # socket closed or failed
            if not self._closed.is_set() and not self._error:
                self._error = f"{type(exc).__name__}: {exc}"
        finally:
            self._closed.set()

    def _keepalive(self) -> None:
        while not self._closed.wait(8):
            try:
                self._ws.send('{"type":"KeepAlive"}')
            except Exception:
                return

    def _text(self) -> str:
        with self._lock:
            return " ".join(s for s in [*self._segments, self._current] if s).strip()

    def push_audio(self, chunk: bytes) -> None:
        if chunk and not self._closed.is_set():
            self._ws.send(chunk)

    def partial_transcript(self) -> str:
        return self._text()

    def finalize(self) -> dict[str, Any]:
        try:
            if not self._closed.is_set():
                self._ws.send('{"type":"CloseStream"}')
            self._closed.wait(5)
        except Exception:
            pass
        finally:
            try:
                self._ws.close()
            except Exception:
                pass
        text = self._text()
        if text:
            return {"success": True, "transcript": text, "provider": NAME}
        return {"success": False, "transcript": "", "provider": NAME, "error": self._error or "no speech recognized"}


class ClaudeVoiceProvider(TranscriptionProvider):
    @property
    def name(self) -> str:
        return NAME

    @property
    def display_name(self) -> str:
        return "Claude Voice (Nova 3)"

    def is_available(self) -> bool:
        return bool(shutil.which("security") and shutil.which("ffmpeg"))

    def list_models(self) -> list[dict[str, Any]]:
        return [{"id": "deepgram-nova3", "display": "Deepgram Nova 3"}]

    def default_model(self) -> Optional[str]:
        return "deepgram-nova3"

    @property
    def streaming_capable(self) -> bool:
        return True

    def open_stream_session(self, *, language: Optional[str] = None,
                            prompt: Optional[str] = None) -> TranscriptionStreamSession:
        return _Stream(language)

    def transcribe(self, file_path: str, *, model: Optional[str] = None, language: Optional[str] = None,
                   **extra: Any) -> dict[str, Any]:
        try:
            pcm = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", file_path, "-ac", "1", "-ar", "16000",
                                  "-f", "s16le", "-"], capture_output=True, timeout=60, check=True).stdout
            session = _Stream(language)
            for i in range(0, len(pcm), CHUNK):
                session.push_audio(pcm[i:i + CHUNK])
                time.sleep(0.01)
            return session.finalize()
        except Exception as exc:
            return {"success": False, "transcript": "", "provider": NAME, "error": f"claude-subscription-voice failed: {exc}"}


def register(ctx) -> None:
    ctx.register_transcription_provider(ClaudeVoiceProvider())
