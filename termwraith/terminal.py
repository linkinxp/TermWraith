import string
from functools import lru_cache
from typing import BinaryIO

import asyncssh
import pyte
from rich.style import Style
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widget import Widget

from .store import KNOWN_HOSTS_FILE, Session, known_host_entry, load_config, log_path, stored_host_lines, trust_host

APP_KEYS = {"f2", "f3", "f10", "ctrl+pagedown", "ctrl+pageup"}
SPECIAL_KEYS = {
    "enter": "\r",
    "tab": "\t",
    "shift+tab": "\x1b[Z",
    "backspace": "\x7f",
    "escape": "\x1b",
    "delete": "\x1b[3~",
    "insert": "\x1b[2~",
    "pageup": "\x1b[5~",
    "pagedown": "\x1b[6~",
}
CURSOR_KEYS = {"up": "A", "down": "B", "right": "C", "left": "D", "home": "H", "end": "F"}
# pyte stores private modes shifted left by 5 (DEC private mode 1 = DECCKM)
DECCKM = 1 << 5


def _color(name: str) -> str | None:
    if name == "default":
        return None
    if len(name) == 6 and all(c in string.hexdigits for c in name):
        return f"#{name}"
    if name.startswith("bright"):
        return f"bright_{name[6:]}"
    return {"brown": "yellow"}.get(name, name)


@lru_cache(maxsize=4096)
def _style(fg: str, bg: str, bold: bool, italics: bool, underline: bool, reverse: bool) -> Style:
    return Style(color=_color(fg), bgcolor=_color(bg), bold=bold, italic=italics, underline=underline, reverse=reverse)


class SSHTerminal(Widget, can_focus=True):
    DEFAULT_CSS = "SSHTerminal { height: 1fr; width: 1fr; }"

    class AuthNeeded(Message):
        def __init__(self, terminal: "SSHTerminal") -> None:
            super().__init__()
            self.terminal = terminal

    class HostKeyNeeded(Message):
        def __init__(self, terminal: "SSHTerminal", fingerprint: str, line: str, password: str | None) -> None:
            super().__init__()
            self.terminal = terminal
            self.fingerprint = fingerprint
            self.line = line
            self.password = password

    def __init__(self, target: Session) -> None:
        super().__init__()
        self.target = target
        self.buffer = pyte.Screen(80, 24)
        self._stream = pyte.ByteStream(self.buffer)
        self._conn: asyncssh.SSHClientConnection | None = None
        self._proc: asyncssh.SSHClientProcess | None = None

    def on_mount(self) -> None:
        self.connect()

    def on_unmount(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def connect(self, password: str | None = None) -> None:
        self.run_worker(self._session(password), exclusive=True, exit_on_error=False)

    def resolve_host_key(self, trust: bool, line: str, password: str | None) -> None:
        if not trust:
            self._write("host key rejected")
            return
        trust_host(known_host_entry(self.target.host, self.target.port), line)
        self.connect(password)

    async def _session(self, password: str | None) -> None:
        t = self.target
        entry = known_host_entry(t.host, t.port)
        self._write(f"connecting to {t.user}@{t.host}:{t.port} ...")
        try:
            presented = await asyncssh.get_server_host_key(t.host, port=t.port)
        except (OSError, asyncssh.Error) as exc:
            self._write(f"connection failed: {exc}")
            return
        if presented is None:
            self._write("connection failed: no host key received")
            return
        line = " ".join(presented.export_public_key().decode().split()[:2])
        trusted = stored_host_lines(entry)
        if trusted and line not in trusted:
            self._write(
                f"HOST KEY CHANGED for {entry}; refusing to connect. "
                f"If the change is expected, remove that line from {KNOWN_HOSTS_FILE}"
            )
            return
        if not trusted:
            self.post_message(self.HostKeyNeeded(self, presented.get_fingerprint(), line, password))
            return
        try:
            self._conn = await asyncssh.connect(
                t.host,
                port=t.port,
                username=t.user,
                client_keys=[t.key] if t.key else None,
                password=password,
                known_hosts=str(KNOWN_HOSTS_FILE),
            )
        except asyncssh.PermissionDenied:
            self._write("authentication failed")
            if password is None:
                self.post_message(self.AuthNeeded(self))
            return
        except (OSError, asyncssh.Error) as exc:
            self._write(f"connection failed: {exc}")
            return

        cols, rows = self._dims()
        self.buffer.resize(rows, cols)
        log = None
        try:
            log = self._open_log()
            self._proc = await self._conn.create_process(
                term_type="xterm-256color", term_size=(cols, rows), stderr=asyncssh.STDOUT, encoding=None
            )
            while data := await self._proc.stdout.read(65536):
                self._stream.feed(data)
                if log is not None:
                    log.write(data)
                    log.flush()
                self.refresh()
        except (OSError, asyncssh.Error) as exc:
            self._write(f"session error: {exc}")
        finally:
            self._proc = None
            self._conn.close()
            self._conn = None
            if log is not None:
                log.close()
        self._write("session closed")

    def _open_log(self) -> BinaryIO | None:
        config = load_config()
        if not config.log_enabled:
            return None
        path = log_path(config, self.target.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("ab")

    def _dims(self) -> tuple[int, int]:
        return self.size.width or 80, self.size.height or 24

    def _write(self, text: str) -> None:
        self._stream.feed(f"\r\n[termwraith] {text}\r\n".encode())
        self.refresh()

    def on_resize(self, event: events.Resize) -> None:
        cols, rows = event.size.width, event.size.height
        if cols and rows:
            self.buffer.resize(rows, cols)
            if self._proc is not None:
                self._proc.change_terminal_size(cols, rows)

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    def on_key(self, event: events.Key) -> None:
        if event.key in APP_KEYS:
            return
        data = self._key_data(event)
        if data is None:
            return
        event.stop()
        event.prevent_default()
        if self._proc is not None:
            self._proc.stdin.write(data.encode())

    def _key_data(self, event: events.Key) -> str | None:
        key = event.key
        if key in CURSOR_KEYS:
            prefix = "\x1bO" if DECCKM in self.buffer.mode else "\x1b["
            return prefix + CURSOR_KEYS[key]
        if key in SPECIAL_KEYS:
            return SPECIAL_KEYS[key]
        if key.startswith("ctrl+") and len(key) == 6 and key[5].isalpha():
            return chr(ord(key[5]) - 96)
        if event.character and event.character.isprintable():
            return event.character
        return None

    def render(self) -> Text:
        screen = self.buffer
        cursor = screen.cursor
        show_cursor = self.has_focus and not cursor.hidden
        text = Text(no_wrap=True, overflow="crop", end="")
        for y in range(screen.lines):
            row = screen.buffer[y]
            for x in range(screen.columns):
                ch = row[x]
                at_cursor = show_cursor and x == cursor.x and y == cursor.y
                style = _style(ch.fg, ch.bg, ch.bold, ch.italics, ch.underscore, ch.reverse != at_cursor)
                text.append(ch.data, style)
            if y < screen.lines - 1:
                text.append("\n")
        return text
