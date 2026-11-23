"""Transcript assembly and finalize rules of _Stream, driven by a fake voice_stream socket."""
import json
import queue
import sys
import threading
import types
import unittest
from unittest import mock

import _stubs

voice = _stubs.load("csv_plugin", _stubs.PKG / "__init__.py", _stubs.PKG)
CLOSE = '{"type":"CloseStream"}'


def msg(kind, data=None):
    return json.dumps({"type": kind, **({"data": data} if data is not None else {})})


class FakeSocket:
    """Yields queued server messages; on CloseStream runs `on_close(self)` in a thread, like a server reply."""

    def __init__(self, before=(), on_close=None):
        self.inbox, self.sent, self.on_close, self.closed = queue.Queue(), [], on_close, False
        for m in before:
            self.inbox.put(m)

    def send(self, m):
        if self.closed:
            raise ConnectionError("closed")
        self.sent.append(m)
        if m == CLOSE and self.on_close:
            threading.Thread(target=self.on_close, args=(self,), daemon=True).start()

    def __iter__(self):
        while (m := self.inbox.get()) is not None:
            yield m

    def close(self):
        self.closed = True
        self.inbox.put(None)

    def server_says(self, *msgs):
        for m in msgs:
            self.inbox.put(m)


class StreamTest(unittest.TestCase):
    def setUp(self):
        prof = {"query": {}, "headers": {}, "user_agent": None}
        for target, value in [("load", lambda: prof), ("headers", lambda: {})]:
            p = mock.patch.object(voice.claude_profile, target, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in [("FINALIZE_NO_DATA_S", 0.1), ("FINALIZE_SAFETY_S", 0.5)]:
            p = mock.patch.object(voice, name, value)
            p.start()
            self.addCleanup(p.stop)

    def finalize(self, sock):
        ws_client = types.SimpleNamespace(connect=lambda *a, **k: sock)
        with mock.patch.dict(sys.modules, {"websockets": types.ModuleType("websockets"),
                                           "websockets.sync": types.ModuleType("websockets.sync"),
                                           "websockets.sync.client": ws_client}):
            stream = voice._Stream("ko")
        stream.push_audio(b"\0" * 10)
        return stream.finalize()["transcript"]

    def test_endpoint_after_close_ends_wait_with_all_segments(self):
        sock = FakeSocket([msg("TranscriptText", "a"), msg("TranscriptEndpoint")],
                          on_close=lambda s: s.server_says(msg("TranscriptText", "b"), msg("TranscriptEndpoint")))
        self.assertEqual(self.finalize(sock), "a b")

    def test_silence_after_close_keeps_what_arrived(self):
        sock = FakeSocket([msg("TranscriptText", "a"), msg("TranscriptEndpoint")])
        self.assertEqual(self.finalize(sock), "a")

    def test_pending_interim_counts_as_final(self):
        sock = FakeSocket([msg("TranscriptText", "a"), msg("TranscriptEndpoint"), msg("TranscriptInterim", "b")])
        self.assertEqual(self.finalize(sock), "a b")

    def test_server_closing_returns_text(self):
        sock = FakeSocket([msg("TranscriptText", "a")], on_close=lambda s: s.inbox.put(None))
        self.assertEqual(self.finalize(sock), "a")

    def test_safety_cap_stops_endless_interims(self):
        def drip(s):
            for i in range(100):
                if s.closed:
                    return
                s.server_says(msg("TranscriptInterim", f"x{i}"))
                threading.Event().wait(0.02)
        transcript = self.finalize(FakeSocket(on_close=drip))
        self.assertTrue(transcript.startswith("x"))
        self.assertLess(int(transcript[1:]), 99)  # stopped by FINALIZE_SAFETY_S, not by running out

    def test_nothing_recognized_is_a_failure(self):
        ws_client = types.SimpleNamespace(connect=lambda *a, **k: FakeSocket())
        with mock.patch.dict(sys.modules, {"websockets.sync.client": ws_client,
                                           "websockets": types.ModuleType("websockets"),
                                           "websockets.sync": types.ModuleType("websockets.sync")}):
            result = voice._Stream("ko").finalize()
        self.assertFalse(result["success"])


class ProviderTest(unittest.TestCase):
    def test_available_without_ffmpeg(self):
        with mock.patch.object(voice.shutil, "which", lambda name: "/usr/bin/security" if name == "security" else None):
            self.assertTrue(voice.ClaudeVoiceProvider().is_available())


class HeadersTest(unittest.TestCase):
    def test_headers_combine_token_user_agent_and_profile(self):
        prof = {"query": {}, "headers": {"x-app": "cli"}, "user_agent": "claude-cli/1.0.0 (external, cli)"}
        with mock.patch.object(voice.claude_profile, "load", lambda: prof), \
             mock.patch.object(voice.claude_profile, "token", lambda: "tok"):
            self.assertEqual(voice.claude_profile.headers(),
                             {"Authorization": "Bearer tok", "User-Agent": "claude-cli/1.0.0 (external, cli)", "x-app": "cli"})


if __name__ == "__main__":
    unittest.main()
