import json, subprocess, sys, threading, time, urllib.parse
from websockets.sync.client import connect

tok = json.loads(subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                                capture_output=True, text=True, check=True).stdout)["claudeAiOauth"]["accessToken"]
q = urllib.parse.urlencode(dict(encoding="linear16", sample_rate=16000, channels=1, endpointing_ms=300,
                                utterance_end_ms=1000, language=sys.argv[2] if len(sys.argv) > 2 else "ko",
                                use_conversation_engine="true", stt_provider="deepgram-nova3"))
url = "wss://api.anthropic.com/api/ws/speech_to_text/voice_stream?" + q
pcm = open(sys.argv[1], "rb").read()
t0 = time.time()
try:
    ws = connect(url, additional_headers={"Authorization": f"Bearer {tok}", "User-Agent": "hermes-claude-voice/0.1"},
                 open_timeout=10)
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
