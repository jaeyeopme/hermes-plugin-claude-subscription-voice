"""Connect once to voice_stream using the same profile as the plugin and transcribe a PCM file.

usage: probe.py <file.pcm (16 kHz s16le mono)> [language]
"""
import importlib.util, json, pathlib, sys, threading, time, urllib.parse
from websockets.sync.client import connect

_spec = importlib.util.spec_from_file_location(
    "claude_profile", pathlib.Path(__file__).parent.parent / "claude-subscription-voice" / "claude_profile.py")
claude_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(claude_profile)
prof = claude_profile.load()

q = urllib.parse.urlencode({**prof["query"], "language": sys.argv[2] if len(sys.argv) > 2 else "ko"})
url = f"{claude_profile.URL}?{q}"
print("url:", url)
pcm = open(sys.argv[1], "rb").read()
t0 = time.time()
try:
    ws = connect(url, additional_headers=claude_profile.headers(), open_timeout=10)
except Exception as e:
    print("CONNECT FAILED:", type(e).__name__, getattr(getattr(e, "response", None), "status_code", ""), e); sys.exit(1)
print("connected in %.2fs" % (time.time() - t0))
ws.send('{"type":"KeepAlive"}')

def feed():
    for i in range(0, len(pcm), 3200):  # 100ms chunks, real-time pace
        ws.send(pcm[i:i + 3200]); time.sleep(0.1)
    ws.send('{"type":"CloseStream"}')
threading.Thread(target=feed, daemon=True).start()

final, interim, t_end = [], "", None
try:
    while True:
        m = json.loads(ws.recv(timeout=6))
        if m.get("type") == "TranscriptText":
            interim = m.get("data", ""); print("  interim: %s" % interim)
        elif m.get("type") == "TranscriptEndpoint":
            final.append(interim); interim = ""
        else:
            print("  msg:", m)
except Exception as e:
    print("recv end:", type(e).__name__)
if interim: final.append(interim)
audio_s = len(pcm) / 32000
print("audio %.1fs, total %.1fs (latency after audio end ~%.1fs)" % (audio_s, time.time() - t0, time.time() - t0 - audio_s - 6))
print("FINAL:", " ".join(final))
