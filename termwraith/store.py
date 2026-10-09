import getpass
import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

SESSIONS_FILE = Path(os.environ.get("TERMWRAITH_SESSIONS", Path.home() / ".config/termwraith/sessions.json"))
CONFIG_FILE = Path(os.environ.get("TERMWRAITH_CONFIG", Path.home() / ".config/termwraith/config.json"))
KNOWN_HOSTS_FILE = SESSIONS_FILE.parent / "known_hosts"


@dataclass(frozen=True)
class Session:
    name: str
    host: str
    user: str
    port: int = 22
    key: str | None = None
    folder: str = ""
    jump: str = ""
    forwards: list[str] = field(default_factory=list)
    cert: str | None = None
    reconnect: bool = False
    vault: bool = False

    @property
    def address(self) -> str:
        return f"{self.user}@{self.host}:{self.port}"


@dataclass(frozen=True)
class Config:
    log_enabled: bool = False
    log_dir: str = str(Path.home() / ".local/state/termwraith/logs")
    fg: str = "#A9B7C6"
    bg: str = "#2B2B2B"
    macros: list[dict] = field(default_factory=list)


def load_sessions(path: Path = SESSIONS_FILE) -> list[Session]:
    if not path.exists():
        return []
    return [Session(**entry) for entry in json.loads(path.read_text())]


def write_sessions(sessions: list[Session], path: Path = SESSIONS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(s) for s in sessions], indent=2) + "\n")


def load_config(path: Path = CONFIG_FILE) -> Config:
    if not path.exists():
        return Config()
    data = json.loads(path.read_text())
    return Config(**{f.name: data[f.name] for f in fields(Config) if f.name in data})


def write_config(config: Config, path: Path = CONFIG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n")


def log_path(config: Config, session_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", session_name)
    return Path(config.log_dir).expanduser() / f"{safe_name}-{stamp}.log"


def read_known_hosts() -> list[str]:
    return KNOWN_HOSTS_FILE.read_text().splitlines() if KNOWN_HOSTS_FILE.exists() else []


def write_known_hosts(lines: list[str]) -> None:
    KNOWN_HOSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KNOWN_HOSTS_FILE.write_text("".join(f"{line}\n" for line in lines))


def known_host_entry(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def stored_host_lines(entry: str) -> list[str]:
    return [
        " ".join(parts[1:3])
        for parts in (line.split() for line in read_known_hosts())
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


def parse_forward(text: str) -> tuple[str, int, str, int]:
    parts = text.strip().split(":")
    if len(parts) != 4 or parts[0] not in ("L", "R"):
        raise ValueError(f"bad forward {text!r}: use L:localport:host:remoteport or R:remoteport:host:localport")
    kind, first, host, second = parts
    return kind, int(first), host, int(second)
