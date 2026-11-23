"""Load the plugin without Hermes or websockets: both are replaced by stand-ins."""
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "claude-subscription-voice"

_atp = types.ModuleType("agent.transcription_provider")
_atp.TranscriptionProvider = type("TranscriptionProvider", (), {})
_atp.TranscriptionStreamSession = type("TranscriptionStreamSession", (), {})
sys.modules.setdefault("agent", types.ModuleType("agent"))
sys.modules.setdefault("agent.transcription_provider", _atp)


def load(name: str, path: pathlib.Path, package_dir: pathlib.Path | None = None):
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(package_dir)] if package_dir else None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
