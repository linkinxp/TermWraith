import codecs
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

from .store import (
    KNOWN_HOSTS_FILE,
    Session,
    known_host_entry,
    load_config,
    log_path,
    parse_forward,
    parse_target,
    stored_host_lines,
    trust_host,
)
from .vault import VaultError, load_passwords, save_passwords

APP_KEYS = {"f2", "f3", "f6", "f7", "f8", "f10", "ctrl+b", "ctrl+f", "ctrl+pagedown", "ctrl+pageup"}
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
RECONNECT_DELAY = 5
KEEPALIVE_SECONDS = 30
SCROLLBACK = 5000
WHEEL_LINES = 3


def _color(name: str) -> str | None:
    if name == "default":
        return None
    if name.startswith("#"):
        return name
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
        def __init__(
            self, terminal: "SSHTerminal", host: str, port: int, fingerprint: str, line: str, password: str | None
        ) -> None:
            super().__init__()
            self.terminal = terminal
            self.host = host
            self.port = port
            self.fingerprint = fingerprint
            self.line = line
            self.password = password

    def __init__(self, target: Session, master: str | None = None) -> None:
        super().__init__()
        self.target = target
        self.master = master
        config = load_config()
        self._fg = config.fg
        self._bg = config.bg
        self._macros = {m["key"]: codecs.decode(m["send"], "unicode_escape") for m in config.macros}
        self.buffer = pyte.HistoryScreen(80, 24, history=SCROLLBACK)
        self._stream = pyte.ByteStream(self.buffer)
        self._conn: asyncssh.SSHClientConnection | None = None
        self._jump: asyncssh.SSHClientConnection | None = None
        self._proc: asyncssh.SSHClientProcess | None = None
        self._password: str | None = None
        self._closing = False
        self._offset = 0
        self._sel: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._dragging = False
        self._hits: set[tuple[int, int]] = set()
        self._matches: list[tuple[int, int]] = []
        self._match = -1

    def on_mount(self) -> None:
        self.connect()

    def on_unmount(self) -> None:
        self._closing = True
        self._close_transport()

    def connect(self, password: str | None = None, typed: bool = False) -> None:
        self.run_worker(self._session(password, typed), exclusive=True, exit_on_error=False)

    def resolve_host_key(self, trust: bool, host: str, port: int, line: str, password: str | None) -> None:
        if not trust:
            self._write("host key rejected")
            return
        trust_host(known_host_entry(host, port), line)
        self.connect(password)

    def _close_transport(self) -> None:
        for conn in (self._conn, self._jump):
            if conn is not None:
                conn.close()
        self._conn = None
        self._jump = None

    def _schedule_reconnect(self) -> None:
        if self.target.reconnect and not self._closing:
            self._write(f"reconnecting in {RECONNECT_DELAY} s ...")
            self.set_timer(RECONNECT_DELAY, lambda: self.connect(self._password))

    async def _session(self, password: str | None, typed: bool) -> None:
        t = self.target
        self._write(f"connecting to {t.address} ...")
        if t.jump:
            jump = parse_target(t.jump)
            if not await self._check_host_key(jump.host, jump.port, password):
                return
        if not t.jump and not await self._check_host_key(t.host, t.port, password):
            return

        passwords: dict[str, str] = {}
        if t.vault:
            try:
                passwords = load_passwords(self.master or "")
            except VaultError as exc:
                self._write(f"vault: {exc}")
                return
            password = password or passwords.get(t.address)

        try:
            if t.jump:
                jump = parse_target(t.jump)
                jump_password = passwords.get(jump.address)
                self._jump = await asyncssh.connect(
                    **self._options(jump.host, jump.port, jump.user, t.key, None, jump_password)
                )
            self._conn = await asyncssh.connect(
                **self._options(t.host, t.port, t.user, t.key, t.cert, password), tunnel=self._jump
            )
        except asyncssh.PermissionDenied:
            self._close_transport()
            self._write("authentication failed")
            if not typed:
                self.post_message(self.AuthNeeded(self))
            return
        except (OSError, asyncssh.Error, ValueError) as exc:
            self._close_transport()
            self._write(f"connection failed: {exc}")
            self._schedule_reconnect()
            return

        if typed and password and t.vault and self.master:
            passwords[t.address] = password
            save_passwords(passwords, self.master)
        self._password = password
        await self._forward_ports()

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
            if log is not None:
                log.close()
        self._close_transport()
        self._write("session closed")
        self._schedule_reconnect()

    async def _check_host_key(self, host: str, port: int, password: str | None) -> bool:
        entry = known_host_entry(host, port)
        try:
            presented = await asyncssh.get_server_host_key(host, port=port)
        except (OSError, asyncssh.Error) as exc:
            self._write(f"connection failed: {exc}")
            self._schedule_reconnect()
            return False
        if presented is None:
            self._write("connection failed: no host key received")
            return False
        line = " ".join(presented.export_public_key().decode().split()[:2])
        trusted = stored_host_lines(entry)
        if trusted and line not in trusted:
            self._write(
                f"HOST KEY CHANGED for {entry}; refusing to connect. "
                f"If the change is expected, remove that line from {KNOWN_HOSTS_FILE}"
            )
            return False
        if not trusted:
            self.post_message(self.HostKeyNeeded(self, host, port, presented.get_fingerprint(), line, password))
            return False
        return True

    async def _forward_ports(self) -> None:
        for spec in self.target.forwards:
            try:
                kind, port, host, target_port = parse_forward(spec)
                if kind == "L":
                    await self._conn.forward_local_port("", port, host, target_port)
                else:
                    await self._conn.forward_remote_port("", port, host, target_port)
            except (OSError, asyncssh.Error, ValueError) as exc:
                self._write(f"forward {spec} failed: {exc}")

    @staticmethod
    def _options(
        host: str, port: int, user: str, key: str | None, cert: str | None, password: str | None
    ) -> dict:
        client_keys = None
        if key:
            client_keys = [(key, cert)] if cert else [key]
        return {
            "host": host,
            "port": port,
            "username": user,
            "client_keys": client_keys,
            "password": password,
            "known_hosts": str(KNOWN_HOSTS_FILE),
            "keepalive_interval": KEEPALIVE_SECONDS,
        }

    def _dims(self) -> tuple[int, int]:
        return self.size.width or 80, self.size.height or 24

    def _write(self, text: str) -> None:
        self._stream.feed(f"\r\n[termwraith] {text}\r\n".encode())
        self.refresh()

    def _open_log(self) -> BinaryIO | None:
        config = load_config()
        if not config.log_enabled:
            return None
        path = log_path(config, self.target.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("ab")

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

    def on_paste(self, event: events.Paste) -> None:
        event.stop()
        self._send(event.text)

    def on_key(self, event: events.Key) -> None:
        if event.key in ("shift+pageup", "shift+pagedown"):
            event.stop()
            event.prevent_default()
            step = self.buffer.lines if event.key == "shift+pageup" else -self.buffer.lines
            self._scroll(step)
            return
        if event.key in self._macros:
            event.stop()
            event.prevent_default()
            self._send(self._macros[event.key])
            return
        if event.key in APP_KEYS:
            return
        data = self._key_data(event)
        if data is None:
            return
        event.stop()
        event.prevent_default()
        self._send(data)

    def _send(self, data: str) -> None:
        terminals = self.screen.query(SSHTerminal) if self.app.broadcast else [self]
        for term in terminals:
            if term._proc is not None:
                term._offset = 0
                term._proc.stdin.write(data.encode())

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

    def _total(self) -> int:
        return len(self.buffer.history.top) + self.buffer.lines

    def _row(self, v: int):
        top = self.buffer.history.top
        if v < len(top):
            return top[v]
        return self.buffer.buffer[v - len(top)]

    def _scroll(self, step: int) -> None:
        self._offset = max(0, min(len(self.buffer.history.top), self._offset + step))
        self.refresh()

    def _cell_at(self, event: events.MouseEvent) -> tuple[int, int]:
        v = len(self.buffer.history.top) - self._offset + event.y
        v = max(0, min(self._total() - 1, v))
        return v, max(0, min(self.buffer.columns - 1, event.x))

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self._scroll(WHEEL_LINES)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self._scroll(-WHEEL_LINES)

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        self._dragging = True
        self.capture_mouse()
        cell = self._cell_at(event)
        self._sel = (cell, cell)
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging and self._sel is not None:
            self._sel = (self._sel[0], self._cell_at(event))
            self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.release_mouse()
        anchor, end = self._sel[0], self._cell_at(event)
        self._sel = (min(anchor, end), max(anchor, end))
        if self._sel[0] == self._sel[1]:
            self._sel = None
            self.refresh()
            return
        text = self._selected_text()
        self.app.copy_to_clipboard(text)
        self.app.notify(f"copied {len(text)} characters")
        self.refresh()

    def _selected_text(self) -> str:
        (first_v, first_x), (last_v, last_x) = self._sel
        lines = []
        for v in range(first_v, last_v + 1):
            row = self._row(v)
            start = first_x if v == first_v else 0
            end = last_x if v == last_v else self.buffer.columns - 1
            lines.append("".join(row[x].data for x in range(start, end + 1)).rstrip())
        return "\n".join(lines)

    def search(self, query: str) -> int:
        q = query.lower()
        self._matches = []
        self._hits = set()
        if q:
            cols = self.buffer.columns
            for v in range(self._total()):
                row = self._row(v)
                text = "".join(row[x].data for x in range(cols)).lower()
                start = text.find(q)
                while start != -1:
                    self._matches.append((v, start))
                    self._hits.update((v, x) for x in range(start, start + len(q)))
                    start = text.find(q, start + 1)
        self._match = 0 if self._matches else -1
        if self._matches:
            self._reveal()
        self.refresh()
        return len(self._matches)

    def search_next(self) -> None:
        if self._matches:
            self._match = (self._match + 1) % len(self._matches)
            self._reveal()

    def _reveal(self) -> None:
        v, _ = self._matches[self._match]
        top = len(self.buffer.history.top)
        self._offset = max(0, min(top, top - (v - self.buffer.lines // 2)))
        self.refresh()

    def render(self) -> Text:
        screen = self.buffer
        cursor = screen.cursor
        top = len(screen.history.top)
        first = top - self._offset
        show_cursor = self.has_focus and self._offset == 0 and not cursor.hidden
        sel = self._sel
        text = Text(no_wrap=True, overflow="crop", end="")
        for r in range(screen.lines):
            v = first + r
            row = self._row(v)
            for x in range(screen.columns):
                ch = row[x]
                at_cursor = show_cursor and x == cursor.x and r == cursor.y
                selected = sel is not None and sel[0] <= (v, x) <= sel[1]
                fg = self._fg if ch.fg == "default" else ch.fg
                bg = self._bg if ch.bg == "default" else ch.bg
                invert = ch.reverse != (at_cursor or selected or (v, x) in self._hits)
                text.append(ch.data, _style(fg, bg, ch.bold, ch.italics, ch.underscore, invert))
            if r < screen.lines - 1:
                text.append("\n")
        return text
