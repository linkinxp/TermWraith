import re
from pathlib import Path

from .store import Session

INI_LINE = re.compile(r'^([SDZ]):"(.+?)"=(.*)$')
REG_STR = re.compile(r'^"(.+?)"="(.*)"$')
REG_DWORD = re.compile(r'^"(.+?)"=dword:([0-9A-Fa-f]+)$')
REG_SECTION = re.compile(r"^\[(.+)\]$")
SKIP_NAMES = {"__FOLDER_DATA__"}
PROTOCOLS = {"SSH2": "ssh", "SSH1": "ssh", "Telnet": "telnet", "Serial": "serial"}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace").lstrip("\ufeff")
    return raw.decode("utf-8-sig", errors="replace")


def _parse_ini(text: str) -> dict[str, str | int]:
    values: dict[str, str | int] = {}
    for line in text.splitlines():
        match = INI_LINE.match(line.strip())
        if not match:
            continue
        kind, key, raw = match.groups()
        if kind == "S":
            values[key] = raw
        elif kind == "D":
            values[key] = int(raw, 16)
    return values


def _parse_reg_values(lines: list[str]) -> dict[str, str | int]:
    values: dict[str, str | int] = {}
    for line in lines:
        line = line.strip()
        match = REG_STR.match(line)
        if match:
            values[match.group(1)] = match.group(2).replace(r"\\", "\\").replace(r"\"", '"')
            continue
        match = REG_DWORD.match(line)
        if match:
            values[match.group(1)] = int(match.group(2), 16)
    return values


def _sessions_from_reg(text: str) -> dict[str, dict[str, str | int]]:
    entries: dict[str, dict[str, str | int]] = {}
    current: str | None = None
    lines: list[str] = []

    def flush() -> None:
        if current is not None:
            entries[current] = _parse_reg_values(lines)

    for line in text.splitlines():
        section = REG_SECTION.match(line.strip())
        if section:
            flush()
            key = section.group(1)
            marker = "\\SecureCRT\\Sessions\\"
            current = key.split(marker, 1)[1] if marker in key else None
            lines = []
        else:
            lines.append(line)
    flush()
    return entries


def _collect(root: Path) -> dict[str, dict[str, str | int]]:
    if root.is_dir():
        entries = {}
        for ini in sorted(root.rglob("*.ini")):
            rel = ini.relative_to(root).with_suffix("").as_posix()
            if ini.stem in SKIP_NAMES:
                continue
            entries[rel] = _parse_ini(_read_text(ini))
        return entries
    if root.suffix.lower() == ".reg":
        return _sessions_from_reg(_read_text(root))
    if root.suffix.lower() == ".ini":
        return {root.stem: _parse_ini(_read_text(root))}
    raise ValueError(f"not a SecureCRT session folder, .ini or .reg file: {root}")


def _to_session(path: str, values: dict[str, str | int], defaults: dict[str, str | int]) -> Session | None:
    merged = {**defaults, **values}
    protocol = PROTOCOLS.get(str(merged.get("Protocol Name", "SSH2")))
    if protocol is None:
        return None
    if protocol == "serial":
        host = str(merged.get("Serial Port", ""))
        port = 0
    else:
        host = str(merged.get("Hostname", ""))
        port_key = "[Telnet] Port" if protocol == "telnet" else "[SSH2] Port"
        port = int(merged.get(port_key, 23 if protocol == "telnet" else 22))
    if not host:
        return None
    parts = [p for p in re.split(r"[\\/]", path) if p]
    name, folder = parts[-1], "/".join(parts[:-1])
    return Session(
        name=name,
        host=host,
        user=str(merged.get("Username", "")) if protocol != "serial" else "",
        port=port,
        key=str(merged.get("Identity Filename V2") or merged.get("Identity Filename") or "") or None,
        folder=folder,
        protocol=protocol,
        baud=int(merged.get("Baud Rate", 9600)) if protocol == "serial" else 9600,
    )


def load_securecrt(root: Path) -> list[Session]:
    entries = _collect(root)
    defaults: dict[str, str | int] = {}
    if "Default" in entries:
        defaults = {k: v for k, v in entries.pop("Default").items() if k != "Hostname"}
    sessions = []
    for path, values in entries.items():
        session = _to_session(path, values, defaults)
        if session is not None:
            sessions.append(session)
    return sessions
