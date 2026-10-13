import importlib.util
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .store import SESSIONS_FILE

PLUGINS_DIR = SESSIONS_FILE.parent / "plugins"

_hooks: dict[str, list[Callable]] = defaultdict(list)


class PluginAPI:
    def on_connect(self, fn: Callable[[str], None]) -> None:
        _hooks["connect"].append(fn)

    def on_output(self, fn: Callable[[str, str], None]) -> None:
        _hooks["output"].append(fn)

    def on_close(self, fn: Callable[[str], None]) -> None:
        _hooks["close"].append(fn)


def load_plugins(directory: Path = PLUGINS_DIR) -> list[str]:
    errors = []
    if not directory.is_dir():
        return errors
    for path in sorted(directory.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"termwraith_plugin_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.register(PluginAPI())
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")
    return errors


def wants(event: str) -> bool:
    return bool(_hooks.get(event))


def fire(event: str, *args: str) -> None:
    for fn in list(_hooks.get(event, ())):
        try:
            fn(*args)
        except Exception:
            pass
