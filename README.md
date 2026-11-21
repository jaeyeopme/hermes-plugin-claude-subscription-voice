# hermes-claude-voice

A Hermes speech-to-text (STT) plugin that uses the same endpoint as Claude Code's `/voice`
(Anthropic `voice_stream`, Deepgram Nova 3), authenticated with the local Claude Code login.

> The endpoint is private and sits in a terms-of-service gray area. Use at your own risk.

## Layout

```
claude-subscription-voice/   Hermes plugin (plugin.yaml, __init__.py)
scripts/probe.py             Standalone connection test against the endpoint
fixtures/                    Korean test audio (mp3 / 16 kHz s16le pcm)
```

## Install

```sh
ln -s "$PWD/claude-subscription-voice" ~/.hermes/plugins/claude-subscription-voice
```

`config.yaml`:

```yaml
plugins:
  enabled: [claude-subscription-voice]
stt:
  provider: claude-subscription-voice
  streaming: true
  language: ko
```

Requirements: macOS (Keychain), `ffmpeg`, a logged-in `claude` CLI, and `websockets` in the Hermes runtime.

## How it works

- **Auth**: reads the OAuth access token from the Keychain item `Claude Code-credentials` (read-only).
  Token refresh is left to Claude Code; if it has expired, run `claude` once.
- **Endpoint**: `wss://api.anthropic.com/api/ws/speech_to_text/voice_stream`
  - Query: `encoding=linear16&sample_rate=16000&channels=1&endpointing_ms=300&utterance_end_ms=1000&language=<lang>&use_conversation_engine=true`
  - Headers: `Authorization`, `User-Agent: claude-cli/<local claude --version> (external, cli)`, `x-app: cli`, `anthropic-client-platform: claude_code_cli`
- **Messages**: `KeepAlive`, then binary PCM audio, then `CloseStream`.
  The server replies with `TranscriptText` (cumulative interim) and `TranscriptEndpoint` (final).
- The values above were taken from `claude --debug` (`[voice_stream]` log lines) and the Claude Code binary.
  The only value read locally at runtime is the installed version.
