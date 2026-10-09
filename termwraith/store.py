import getpass
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

SESSIONS_FILE = Path(os.environ.get("TERMWRAITH_SESSIONS", Path.home() / ".config/termwraith/sessions.json"))
CONFIG_FILE = Path(os.environ.get("TERMWRAITH_CONFIG", Path.home() / ".config/termwraith/config.json"))


@dataclass(frozen=True)
class Session:
    name: str
    host: str
    user: str
    port: int = 22
    key: str | None = None
    folder: str = ""


def load_sessions(path: Path = SESSIONS_FILE) -> list[Session]:
    if not path.exists():
        return []
    return [Session(**entry) for entry in json.loads(path.read_text())]


def write_sessions(sessions: list[Session], path: Path = SESSIONS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(s) for s in sessions], indent=2) + "\n")


@dataclass(frozen=True)
class Config:
    log_enabled: bool = False
    log_dir: str = str(Path.home() / ".local/state/termwraith/logs")


def load_config(path: Path = CONFIG_FILE) -> Config:
    if not path.exists():
        return Config()
    data = json.loads(path.read_text())
    return Config(**{key: data[key] for key in ("log_enabled", "log_dir") if key in data})


def write_config(config: Config, path: Path = CONFIG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n")


def log_path(config: Config, session_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", session_name)
    return Path(config.log_dir).expanduser() / f"{safe_name}-{stamp}.log"


KNOWN_HOSTS_FILE = SESSIONS_FILE.parent / "known_hosts"


def known_host_entry(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def stored_host_lines(entry: str) -> list[str]:
    if not KNOWN_HOSTS_FILE.exists():
        return []
    return [
        " ".join(parts[1:3])
        for parts in (line.split() for line in KNOWN_HOSTS_FILE.read_text().splitlines())
        if parts[:1] == [entry]
    ]


def trust_host(entry: str, key_line: str) -> None:
    KNOWN_HOSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with KNOWN_HOSTS_FILE.open("a") as fh:
        fh.write(f"{entry} {key_line}\n")


def parse_target(text: str) -> Session:
    user, sep, hostport = text.rpartition("@")
    if not sep:
        user, hostport = getpass.getuser(), text
    host, _, port = hostport.partition(":")
    return Session(name=text, host=host, user=user, port=int(port or 22))
