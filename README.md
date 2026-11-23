# hermes-plugin-claude-subscription-voice

A [Hermes](https://github.com/NousResearch/hermes-agent) speech-to-text (STT) plugin that uses the same endpoint as
Claude Code's `/voice` (Anthropic `voice_stream`, Deepgram Nova 3), authenticated with your local Claude Code login.
No extra API key: if `claude` works on your Mac, so does this.

> The endpoint is private and undocumented, and using it outside Claude Code sits in a terms-of-service gray area.
> It can change or stop working at any time. Use at your own risk.

## What it does

- Registers the `claude-subscription-voice` transcription provider in Hermes.
- **Streaming**: live microphone audio with partial transcripts while you speak.
- **Files**: any audio file ffmpeg can read, converted to 16 kHz mono PCM and sent in one go.

## Requirements

- macOS (the login token is read from the Keychain)
- Hermes `>=0.22.4`, installed with the official installer
- Claude Code installed and logged in (`claude` on `PATH`)
- `ffmpeg`, for file transcription only

## Install

```sh
hermes plugins install jaeyeopme/hermes-plugin-claude-subscription-voice --enable
```

Or from a clone, for development:

```sh
ln -s "$PWD" ~/.hermes/plugins/claude-subscription-voice
hermes plugins enable claude-subscription-voice
```

## Configuration

`config.yaml`:

```yaml
stt:
  provider: claude-subscription-voice
  streaming: true
  language: ko
```

`language` takes a language code; a region suffix is ignored (`en-US` → `en`). Supported:
`en es fr ja de pt it ko hi id ru pl tr nl uk el cs da sv no`. An unset or unsupported value falls back to `ko`.

## Check the connection

`scripts/probe.py` connects once with the same profile as the plugin and transcribes a 16 kHz s16le mono PCM file:

```sh
python scripts/probe.py fixtures/ko_test.pcm ko
```

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `Claude Code login not found in Keychain` | Not logged in: run `claude auth login`. |
| `Claude Code token expired` | The plugin never refreshes the token itself. Run `claude` once and it refreshes it. |
| `voice_stream profile differs from the built-in defaults` | Claude Code changed its connect parameters. The parsed values are used; open an issue if transcription breaks. |
| `claude CLI not found on PATH; using defaults` | Hermes cannot see `claude`. Defaults are used and no User-Agent is sent until Hermes restarts with `claude` on `PATH`. |
| `no speech recognized` | No transcript arrived: check the language setting and that the audio is not silent. |

## Privacy

- Reads the Claude Code OAuth token from the Keychain item `Claude Code-credentials`, read-only, and sends it only to `api.anthropic.com`.
- Audio goes to Anthropic's `voice_stream` endpoint, the same place Claude Code's `/voice` sends it. Nothing is stored locally.

## How it works

- **Auth**: reads the OAuth access token from the Keychain item `Claude Code-credentials` (read-only).
  Token refresh is left to Claude Code; if it has expired, run `claude` once.
- **Endpoint**: `wss://api.anthropic.com/api/ws/speech_to_text/voice_stream`
  - Query: `encoding=linear16&sample_rate=16000&channels=1&endpointing_ms=300&utterance_end_ms=1000&language=<lang>&use_conversation_engine=true`
  - Headers: `Authorization`, `User-Agent: claude-cli/<local claude --version> (external, cli)`, `x-app: cli`, `anthropic-client-platform: claude_code_cli`
- **Messages**: `KeepAlive`, then binary PCM audio, then `CloseStream`.
  The server replies with `TranscriptText` (cumulative interim) and `TranscriptEndpoint` (final).
- **Nothing is hard-coded.** `claude_profile.py` parses the connect parameters (query, static headers,
  client platform, UA format) out of the installed `claude` binary and reads the version from
  `claude --version`. This runs once per process when the plugin loads (~0.3 s). If `claude` cannot be found or parsed then,
  the built-in defaults (and no User-Agent) are used until Hermes restarts, so the plugin follows the Claude Code
  version installed when Hermes started. `scripts/probe.py` uses the same loader.

## Uninstall

```sh
hermes plugins remove claude-subscription-voice
```

Then set `stt.provider` back to another provider.

## Development

```
plugin.yaml, __init__.py, claude_profile.py   Hermes plugin
scripts/probe.py                            Standalone connection test against the endpoint
fixtures/                                   Korean test audio (mp3 / 16 kHz s16le pcm)
tests/                                      Offline tests with fake sockets, no Hermes needed
```

```sh
python3 -m unittest discover tests
```

## License

[MIT](LICENSE)
