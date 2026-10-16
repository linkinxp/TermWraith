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
    protocol: str = "ssh"
    baud: int = 9600
    script: list[str] = field(default_factory=list)
    has_script: bool = False
    colour_scheme: str = ""
    scrollback: int = 5000

    @property
    def address(self) -> str:
        if self.protocol == "serial":
            return self.host
        return f"{self.user}@{self.host}:{self.port}" if self.user else f"{self.host}:{self.port}"


@dataclass(frozen=True)
class Config:
    log_enabled: bool = False
    highlight_words: bool = True
    log_dir: str = str(Path.home() / ".local/state/termwraith/logs")
    theme: str = "termix"
    fg: str = ""
    bg: str = ""
    macros: list[dict] = field(default_factory=list)
    log_template: str = "{session}-{stamp}.log"
    schemes: dict[str, list[str]] = field(default_factory=dict)
    recent: list[str] = field(default_factory=list)


def load_sessions(path: Path = SESSIONS_FILE) -> list[Session]:
    if not path.exists():
        return []
    return [Session(**entry) for entry in json.loads(path.read_text())]


def write_sessions(sessions: list[Session], path: Path = SESSIONS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for s in sessions:
        entry = asdict(s)
        if s.has_script:
            entry.pop("script")
        entries.append(entry)
    path.write_text(json.dumps(entries, indent=2) + "\n")


def load_config(path: Path = CONFIG_FILE) -> Config:
    if not path.exists():
        return Config()
    data = json.loads(path.read_text())
    return Config(**{f.name: data[f.name] for f in fields(Config) if f.name in data})


def write_config(config: Config, path: Path = CONFIG_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2) + "\n")


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def log_path(config: Config, target: Session) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = config.log_template.format(session=_safe(target.name), host=_safe(target.host), stamp=stamp)
    return Path(config.log_dir).expanduser() / _safe(name)


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
    if len(parts) == 2 and parts[0] == "D" and parts[1].isdigit():
        return "D", int(parts[1]), "", 0
    if len(parts) != 4 or parts[0] not in ("L", "R"):
        raise ValueError(
            f"bad forward {text!r}: use L:localport:host:remoteport, R:remoteport:host:localport or D:localport"
        )
    kind, first, host, second = parts
    return kind, int(first), host, int(second)
