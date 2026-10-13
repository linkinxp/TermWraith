import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult, SystemCommand
from textual.events import Key
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    Select,
    Switch,
    TabbedContent,
    TabPane,
    TextArea,
    Tree,
)
from textual.widgets.tree import TreeNode

from .store import (
    Config,
    Session,
    load_config,
    load_sessions,
    parse_forward,
    parse_target,
    read_known_hosts,
    write_config,
    write_known_hosts,
    write_sessions,
)
from .resources import ResourcesScreen
from .securecrt import load_global_config, load_securecrt
from .sftp import SftpScreen
from .terminal import SSHTerminal
from . import plugins
from .plugins import Context, load_plugins
from .tui_themes import tui_themes
from .vault import VaultError, forget, load_passwords, load_script, set_script

DARCULA = Theme(
    name="darcula",
    primary="#6897BB",
    secondary="#A9B7C6",
    accent="#CC7832",
    foreground="#A9B7C6",
    background="#2B2B2B",
    surface="#3C3F41",
    panel="#313335",
    warning="#FFC66D",
    error="#FF6B68",
    success="#6A8759",
    dark=True,
)
TUI_THEMES = tui_themes()
DARK_THEMES = ["darcula", "nord", "gruvbox", "catppuccin-mocha", "dracula", "tokyo-night", "monokai", "rose-pine", "solarized-dark", "atom-one-dark", *(t.name for t in TUI_THEMES)]
LIGHT_THEMES = ["textual-light", "catppuccin-latte", "solarized-light", "rose-pine-dawn", "atom-one-light"]
THEME_CHOICES = [
    (f"{name.replace('-', ' ').title()}  (dark)", name) for name in DARK_THEMES
] + [
    (f"{name.replace('-', ' ').title()}  (light)", name) for name in LIGHT_THEMES
]


class HostKeyScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "reject", "Reject")]

    def __init__(self, host: str, port: int, fingerprint: str) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._fingerprint = fingerprint

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(f"Unknown host {self._host}:{self._port}")
            yield Label(f"Fingerprint: {self._fingerprint}")
            yield Label("Trust this host key and save it?")
            with Horizontal(classes="buttons"):
                yield Button("Trust & save", variant="success", id="trust")
                yield Button("Reject", variant="error", id="reject")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "trust")

    def action_reject(self) -> None:
        self.dismiss(False)


class TextPrompt(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str, value: str = "") -> None:
        super().__init__()
        self._label = label
        self._value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(self._label)
            yield Input(value=self._value, id="text")

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


DEFAULT_PORTS = {"ssh": "22", "telnet": "23"}
HEX_COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class SessionForm(ModalScreen[Session | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: Session | None = None, folder: str = "") -> None:
        super().__init__()
        self._session = session
        self._folder = folder

    def compose(self) -> ComposeResult:
        s = self._session
        with Vertical(id="form-box") as box:
            box.border_title = "Edit session" if s else "New session"
            with VerticalScroll(id="form-body"):
                with Horizontal(classes="pair"):
                    with Vertical(classes="field"):
                        yield Label("Name")
                        yield Input(value=s.name if s else "", placeholder="optional", id="name")
                    with Vertical(classes="field"):
                        yield Label("Folder")
                        yield Input(value=s.folder if s else self._folder, placeholder="Clients/Acme", id="folder")
                with Horizontal(classes="pair"):
                    with Vertical(classes="field"):
                        yield Label("Protocol")
                        yield Select(
                            [("SSH", "ssh"), ("Telnet", "telnet"), ("Serial", "serial")],
                            value=s.protocol if s else "ssh",
                            allow_blank=False,
                            id="protocol",
                        )
                    with Vertical(classes="field"):
                        yield Label("Baud rate (serial)")
                        yield Input(value=str(s.baud) if s else "9600", placeholder="9600", id="baud")
                with Horizontal(classes="pair"):
                    with Vertical(classes="field wide"):
                        yield Label("Host")
                        yield Input(value=s.host if s else "", placeholder="10.0.0.5", id="host")
                    with Vertical(classes="field narrow"):
                        yield Label("Port")
                        yield Input(value=str(s.port) if s else "22", placeholder="22", id="port")
                with Horizontal(classes="pair"):
                    with Vertical(classes="field"):
                        yield Label("User")
                        yield Input(value=s.user if s else "", placeholder="deploy", id="user")
                    with Vertical(classes="field"):
                        yield Label("Key file")
                        yield Input(value=(s.key or "") if s else "", placeholder="~/.ssh/id_ed25519", id="key")
                with Horizontal(classes="pair"):
                    with Vertical(classes="field"):
                        yield Label("Certificate")
                        yield Input(value=(s.cert or "") if s else "", placeholder="id_ed25519-cert.pub", id="cert")
                    with Vertical(classes="field"):
                        yield Label("Jump host")
                        yield Input(value=s.jump if s else "", placeholder="user@bastion:22", id="jump")
                with Vertical(classes="field full"):
                    yield Label("Forwards")
                    yield Input(
                        value=", ".join(s.forwards) if s else "",
                        placeholder="L:8080:db:5432, R:9000:localhost:3000, D:1080",
                        id="forwards",
                    )
                with Vertical(classes="field full"):
                    yield Label("Logon script  expect TEXT / send TEXT / wait SECONDS, one per line")
                    yield TextArea("\n".join(s.script) if s else "", id="script")
                with Horizontal(classes="pair switches"):
                    with Horizontal(classes="switch"):
                        yield Switch(value=s.reconnect if s else False, id="reconnect")
                        yield Label("Auto-reconnect")
                    with Horizontal(classes="switch"):
                        yield Switch(value=s.vault if s else False, id="vault")
                        yield Label("Store password in vault")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="success", id="save")
                yield Button("Cancel", id="cancel")

    @on(Select.Changed, "#protocol")
    def _protocol_changed(self, event: Select.Changed) -> None:
        port = self.query_one("#port", Input)
        if port.value.strip() in DEFAULT_PORTS.values():
            port.value = DEFAULT_PORTS.get(str(event.value), port.value)

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        host = self.query_one("#host", Input).value.strip()
        user = self.query_one("#user", Input).value.strip()
        port_text = self.query_one("#port", Input).value.strip() or "22"
        protocol = str(self.query_one("#protocol", Select).value)
        if not host or (protocol == "ssh" and not user):
            self.notify("Host and user are required" if protocol == "ssh" else "Host is required", severity="error")
            return
        if not port_text.isdigit() or not 0 < int(port_text) < 65536:
            self.notify("Port must be between 1 and 65535", severity="error")
            return
        baud_text = self.query_one("#baud", Input).value.strip() or "9600"
        if not baud_text.isdigit() or int(baud_text) <= 0:
            self.notify("Baud rate must be a positive number", severity="error")
            return
        script = [line.strip() for line in self.query_one("#script", TextArea).text.splitlines() if line.strip()]
        jump = self.query_one("#jump", Input).value.strip()
        if jump:
            try:
                parse_target(jump)
            except ValueError:
                self.notify("Jump host port must be a number", severity="error")
                return
        forwards = [part.strip() for part in self.query_one("#forwards", Input).value.split(",") if part.strip()]
        for spec in forwards:
            try:
                parse_forward(spec)
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return
        name = self.query_one("#name", Input).value.strip() or f"{user}@{host}"
        key_text = self.query_one("#key", Input).value.strip()
        key = str(Path(key_text).expanduser()) if key_text else None
        cert_text = self.query_one("#cert", Input).value.strip()
        cert = str(Path(cert_text).expanduser()) if cert_text else None
        folder = "/".join(part.strip() for part in self.query_one("#folder", Input).value.split("/") if part.strip())
        self.dismiss(
            Session(
                name=name,
                host=host,
                user=user,
                port=int(port_text),
                key=key,
                folder=folder,
                jump=jump,
                forwards=forwards,
                cert=cert,
                reconnect=self.query_one("#reconnect", Switch).value,
                vault=self.query_one("#vault", Switch).value,
                protocol=protocol,
                baud=int(baud_text),
                script=script,
            )
        )

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label("Settings")
            with Horizontal(classes="row"):
                yield Switch(value=self._config.log_enabled, id="log-enabled")
                yield Label("Log session output")
                yield Switch(value=self._config.highlight_words, id="highlight-words")
                yield Label("Highlight network words")
            yield Label("Log directory")
            yield Input(value=self._config.log_dir, id="log-dir")
            yield Label("Log filename, placeholders {session} {host} {stamp}")
            yield Input(value=self._config.log_template, id="log-template")
            yield Label("Theme")
            yield Select(THEME_CHOICES, value=self._config.theme, allow_blank=False, id="theme")
            with Horizontal(classes="pair"):
                with Vertical(classes="field"):
                    yield Label("Text colour (blank = theme)")
                    yield Input(value=self._config.fg, placeholder="app theme", id="fg")
                with Vertical(classes="field"):
                    yield Label("Background (blank = theme)")
                    yield Input(value=self._config.bg, placeholder="app theme", id="bg")
            yield Label("Macros, one per line: key = text  (e.g. f5 = ls -la\\r)")
            yield TextArea(
                "\n".join(f"{m['key']} = {m['send']}" for m in self._config.macros), id="macros"
            )
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="success", id="save")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        directory = self.query_one("#log-dir", Input).value.strip()
        if not directory:
            self.notify("Log directory is required", severity="error")
            return
        template = self.query_one("#log-template", Input).value.strip()
        try:
            template.format(session="x", host="x", stamp="x")
        except (KeyError, IndexError, ValueError):
            self.notify("Log filename may only use {session}, {host} and {stamp}", severity="error")
            return
        if not template:
            self.notify("Log filename is required", severity="error")
            return
        fg = self.query_one("#fg", Input).value.strip()
        bg = self.query_one("#bg", Input).value.strip()
        if not all((not fg or HEX_COLOUR.match(fg), not bg or HEX_COLOUR.match(bg))):
            self.notify("Colours must be #RRGGBB", severity="error")
            return
        macros = []
        for line in self.query_one("#macros", TextArea).text.splitlines():
            if not line.strip():
                continue
            key, sep, send = line.partition("=")
            if not sep or not key.strip() or not send.strip():
                self.notify(f"Macro needs 'key = text': {line.strip()}", severity="error")
                return
            macros.append({"key": key.strip(), "send": send.strip()})
        enabled = self.query_one("#log-enabled", Switch).value
        theme = self.query_one("#theme", Select).value
        write_config(
            replace(
                self._config,
                log_enabled=enabled,
                highlight_words=self.query_one("#highlight-words", Switch).value,
                log_dir=directory,
                log_template=template,
                theme=theme,
                fg=fg,
                bg=bg,
                macros=macros,
            )
        )
        self.app.theme = theme
        self.dismiss(None)

    @on(Select.Changed, "#theme")
    def _preview_theme(self, event: Select.Changed) -> None:
        self.app.theme = event.value

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.app.theme = self._config.theme
        self.dismiss(None)


class HostsScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "cancel", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._lines = read_known_hosts()

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label("Known hosts (highlight a line, then Remove)")
            if not self._lines:
                yield Label("No known hosts yet. Hosts are saved on first connect.")
            yield OptionList(*self._lines, id="hosts-list")
            with Horizontal(classes="buttons"):
                yield Button("Remove", variant="error", id="remove")
                yield Button("Close", id="close")

    @on(Button.Pressed, "#remove")
    def _remove(self) -> None:
        options = self.query_one("#hosts-list", OptionList)
        index = options.highlighted
        if index is None:
            return
        del self._lines[index]
        write_known_hosts(self._lines)
        options.remove_option_at_index(index)

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Picker(ModalScreen[Session | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._sessions = load_sessions()
        self._recall = -1

    def compose(self) -> ComposeResult:
        with Vertical(id="box") as box:
            box.border_title = "Sessions"
            yield Input(placeholder="Search sessions", id="filter")
            yield Tree("Sessions", id="saved")
            with Horizontal(classes="buttons"):
                yield Button("New", variant="primary", id="new")
                yield Button("Edit", id="edit")
                yield Button("Delete", variant="error", id="delete")
            with Horizontal(classes="buttons second"):
                yield Button("Hosts", id="hosts")
                yield Button("Export", id="export")
                yield Button("Import", id="import")
                yield Button("Settings", id="settings")
            yield Input(placeholder="Quick connect  deploy@10.0.0.5:2222", id="quick")

    def on_mount(self) -> None:
        self._reload()

    def _reload(self) -> None:
        tree = self.query_one("#saved", Tree)
        tree.clear()
        tree.show_root = False
        tree.root.expand()
        folders: dict[str, TreeNode] = {"": tree.root}
        terms = self.query_one("#filter", Input).value.lower().split()
        ordered = sorted(enumerate(self._sessions), key=lambda pair: (pair[1].folder.lower(), pair[1].name.lower()))
        for index, session in ordered:
            haystack = " ".join((session.name, session.host, session.user, session.folder, session.protocol)).lower()
            if not all(term in haystack for term in terms):
                continue
            parent = self._folder_node(folders, session.folder)
            parent.add_leaf(f"{session.name}  ({session.address})", data=index)

    def _folder_node(self, folders: dict[str, TreeNode], path: str) -> TreeNode:
        if path not in folders:
            parent_path, _, leaf = path.rpartition("/")
            folders[path] = self._folder_node(folders, parent_path).add(leaf, data=path, expand=True)
        return folders[path]

    def _selected_index(self) -> int | None:
        node = self.query_one("#saved", Tree).cursor_node
        return node.data if node is not None and isinstance(node.data, int) else None

    def _cursor_folder(self) -> str:
        node = self.query_one("#saved", Tree).cursor_node
        if node is None or node.data is None:
            return ""
        if isinstance(node.data, str):
            return node.data
        return self._sessions[node.data].folder

    @on(Tree.NodeSelected)
    def _picked(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, int):
            self.dismiss(self._sessions[event.node.data])

    @on(Button.Pressed, "#new")
    def _new(self) -> None:
        self.app.push_screen(SessionForm(folder=self._cursor_folder()), self._add)

    def _add(self, session: Session | None) -> None:
        if session is None:
            return
        self._save(session, None, None)

    @on(Button.Pressed, "#edit")
    def _edit(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        old = self._sessions[index]

        def open_form(master: str | None) -> None:
            shown = replace(old, script=load_script(master, old.name)) if old.has_script else old
            self.app.push_screen(SessionForm(shown), lambda session: self._save(session, old, index))

        if old.has_script:
            self.app.with_master(open_form)
        else:
            open_form(None)

    def _save(self, session: Session | None, old: Session | None, index: int | None) -> None:
        if session is None:
            return
        needs_vault = bool(session.script or (old and (old.has_script or old.script)))

        def write(master: str | None) -> None:
            if needs_vault:
                set_script(master, session.name, session.script, old.name if old else None)
            stored = replace(session, has_script=bool(session.script), script=[])
            if index is None:
                self._sessions.append(stored)
            else:
                self._sessions[index] = stored
            write_sessions(self._sessions)
            self._reload()

        if needs_vault:
            self.app.with_master(write)
        else:
            write(None)

    @on(Button.Pressed, "#settings")
    def _settings(self) -> None:
        self.app.push_screen(SettingsScreen(load_config()))

    @on(Button.Pressed, "#hosts")
    def _hosts(self) -> None:
        self.app.push_screen(HostsScreen())

    @on(Button.Pressed, "#export")
    def _export(self) -> None:
        self.app.push_screen(
            TextPrompt("Export sessions to file", str(Path.home() / "termwraith-sessions.json")), self._do_export
        )

    def _do_export(self, path: str | None) -> None:
        if not path:
            return
        target = Path(path).expanduser()
        if any(s.has_script for s in self._sessions):
            self.app.with_master(lambda master: self._write_export(target, master))
        else:
            self._write_export(target, None)

    def _write_export(self, target: Path, master: str | None) -> None:
        out = [replace(s, script=load_script(master, s.name), has_script=False) if s.has_script else s for s in self._sessions]
        write_sessions(out, target)
        self.notify(f"exported {len(out)} sessions; logon scripts are in plain text, keep the file private", severity="warning")

    @on(Button.Pressed, "#import")
    def _import(self) -> None:
        self.app.push_screen(
            TextPrompt("Import: termwraith JSON, SecureCRT Sessions folder/.ini/.reg, or Global.ini"),
            self._do_import,
        )

    def _do_import(self, path: str | None) -> None:
        if not path:
            return
        source = Path(path).expanduser()
        if source.name.lower() == "global.ini":
            self._import_global(source)
            return
        try:
            if source.is_dir() or source.suffix.lower() in (".ini", ".reg"):
                incoming = load_securecrt(source)
            else:
                incoming = load_sessions(source)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.notify(f"import failed: {exc}", severity="error")
            return
        known = {(s.name, s.user, s.host, s.port) for s in self._sessions}
        added = [s for s in incoming if (s.name, s.user, s.host, s.port) not in known]
        if any(s.script for s in added):
            self.app.with_master(lambda master: self._finish_import(added, master))
        else:
            self._finish_import(added, None)

    def _import_global(self, source: Path) -> None:
        try:
            found = load_global_config(source)
        except (OSError, ValueError) as exc:
            self.notify(f"import failed: {exc}", severity="error")
            return
        if not found:
            self.notify("no importable settings in that Global.ini", severity="warning")
            return
        config = load_config()
        if "schemes" in found:
            found["schemes"] = {**config.schemes, **found["schemes"]}
        write_config(replace(config, **found))
        self.notify(f"imported {', '.join(sorted(found))} from SecureCRT; new tabs use the new colours")

    def _finish_import(self, added: list[Session], master: str | None) -> None:
        for s in added:
            if s.script:
                set_script(master, s.name, s.script)
            self._sessions.append(replace(s, has_script=bool(s.script), script=[]))
        write_sessions(self._sessions)
        self._reload()
        self.notify(f"imported {len(added)} sessions")

    @on(Button.Pressed, "#delete")
    def _delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        old = self._sessions[index]

        def remove(master: str | None) -> None:
            del self._sessions[index]
            if master is not None:
                script_name = None if any(s.name == old.name and s.has_script for s in self._sessions) or not old.has_script else old.name
                shared = any(s.address == old.address for s in self._sessions)
                forget(master, script_name, None if shared or not old.vault else old.address)
            write_sessions(self._sessions)
            self._reload()

        if old.has_script or old.vault:
            self.app.with_master(remove)
        else:
            remove(None)

    @on(Input.Changed, "#filter")
    def _filter_changed(self) -> None:
        self._reload()

    @on(Input.Submitted, "#filter")
    def _filter_submitted(self) -> None:
        self.query_one("#saved", Tree).focus()

    @on(Input.Submitted, "#quick")
    def _quick(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return
        try:
            target = parse_target(value)
        except ValueError:
            self.notify("Port must be a number", severity="error")
            return
        config = load_config()
        write_config(replace(config, recent=[value, *(v for v in config.recent if v != value)][:10]))
        self.dismiss(target)

    def on_key(self, event: Key) -> None:
        quick = self.query_one("#quick", Input)
        recent = load_config().recent
        if self.focused is not quick or event.key not in ("up", "down") or not recent:
            return
        self._recall = max(-1, min(len(recent) - 1, self._recall + (1 if event.key == "up" else -1)))
        quick.value = recent[self._recall] if self._recall >= 0 else ""
        quick.cursor_position = len(quick.value)
        event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)


class PasswordPrompt(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str) -> None:
        super().__init__()
        self._label = label

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(self._label)
            yield Input(password=True, id="pw")

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SearchResults(ModalScreen[int | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, rows: list[str]) -> None:
        super().__init__()
        self._rows = rows

    def compose(self) -> ComposeResult:
        with Vertical(id="box") as box:
            box.border_title = f"{len(self._rows)} matches in open tabs"
            yield OptionList(*self._rows, id="hits")

    @on(OptionList.OptionSelected)
    def _pick(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_index)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TermWraith(App):
    TITLE = "termwraith"
    SUB_TITLE = "SSH · telnet · serial"
    CSS = """
    #box {
        width: 78;
        height: auto;
        max-height: 90%;
        border: round $primary;
        border-title-color: $accent;
        border-title-style: bold;
        background: $surface;
        padding: 1 2;
    }
    #form-box { width: 96; height: 95%; border: round $primary; border-title-color: $accent; border-title-style: bold; background: $surface; padding: 1 2; }
    #form-body { height: 1fr; }
    .pair { height: auto; }
    #macros { height: 4; }
    .field { width: 1fr; height: auto; margin-right: 2; }
    .field.narrow { width: 14; }
    .field.full { width: 100%; margin-right: 0; }
    .field Label { color: $text-muted; }
    .switches { margin-top: 1; height: auto; }
    .switch { width: 1fr; height: auto; }
    .switch Label { margin-top: 1; color: $text; }
    .switch Switch { margin-top: 0; }
    #script { height: 4; }
    #sftp-box { width: 90%; height: 80%; border: thick $accent; background: $surface; padding: 1 2; }
    #sftp-list { height: 1fr; }
    SftpScreen { align: center middle; }
    ResourcesScreen { align: center middle; }
    #res-box { width: 70; height: auto; border: thick $accent; background: $surface; padding: 1 2; }
    SearchResults { align: center middle; }
    #hits { width: 100%; height: auto; max-height: 20; }
    #filter { margin-bottom: 1; border: round $primary-darken-2; }
    #filter:focus { border: round $accent; }
    #saved { height: 14; background: $panel; padding: 0 1; }
    #quick { margin-top: 1; border: round $primary-darken-2; }
    #quick:focus { border: round $accent; }
    #hosts-list { height: 12; }
    .buttons { height: auto; margin-top: 1; }
    .buttons.second { margin-top: 0; }
    .buttons Button { height: 1; min-width: 9; border: none; margin-right: 2; padding: 0 1; }
    .buttons Button:focus { text-style: bold reverse; }
    .row { height: auto; }
    .row Label { padding: 1 0 0 1; }
    Picker, PasswordPrompt, HostKeyScreen, SessionForm, SettingsScreen, HostsScreen, TextPrompt { align: center middle; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; height: 1fr; }
    .split { height: 1fr; }
    """
    BINDINGS = [
        Binding("f2", "connect", "Connect"),
        Binding("f3", "close_tab", "Close tab"),
        Binding("f6", "split", "Split"),
        Binding("f7", "rename", "Rename"),
        Binding("f8", "search_next", "Next", show=False),
        Binding("f4", "resources", "Resources"),
        Binding("f9", "sftp", "SFTP"),
        Binding("ctrl+f", "search", "Find"),
        Binding("f5", "search_all", "Find in tabs"),
        Binding("ctrl+b", "broadcast", "Broadcast"),
        Binding("ctrl+pagedown", "cycle_tab(1)", "Next tab", show=False),
        Binding("ctrl+pageup", "cycle_tab(-1)", "Prev tab", show=False),
        Binding("f10", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._tab_seq = 0
        self._master: str | None = None
        self.broadcast = False
        self.register_theme(DARCULA)
        for theme in TUI_THEMES:
            self.register_theme(theme)
        theme = load_config().theme
        self.theme = theme if theme in self.available_themes else DARCULA.name

    def compose(self) -> ComposeResult:
        yield Header(icon="◆")
        yield TabbedContent()
        yield Footer()

    def on_mount(self) -> None:
        for error in load_plugins():
            self.notify(f"Plugin not loaded, {error}", severity="error", timeout=10)
        for index, (title, _fn, key) in enumerate(plugins.commands):
            if key:
                self.bind(key, f"plugin_command({index})", description=title, show=False)
        if any(s.script for s in load_sessions()):
            self.with_master(self._migrate_scripts, cancelled=self.action_connect)
        else:
            self.action_connect()

    def _migrate_scripts(self, master: str | None) -> None:
        sessions = load_sessions()
        migrated = []
        for s in sessions:
            if s.script:
                set_script(master, s.name, s.script)
                s = replace(s, has_script=True, script=[])
            migrated.append(s)
        write_sessions(migrated)
        self.action_connect()

    def with_master(self, then: Callable[[str | None], None], cancelled: Callable[[], None] | None = None) -> None:
        if self._master is not None:
            then(self._master)
            return
        self.push_screen(PasswordPrompt("Vault master password"), lambda pw: self._check_master(pw, then, cancelled))

    def _check_master(self, master: str | None, then: Callable[[str | None], None], cancelled: Callable[[], None] | None) -> None:
        if master is None:
            if cancelled is not None:
                cancelled()
            return
        try:
            load_passwords(master)
        except VaultError:
            self.notify("wrong vault master password", severity="error")
            self.with_master(then, cancelled)
            return
        self._master = master
        then(master)

    def action_connect(self) -> None:
        self.push_screen(Picker(), self._open)

    def _open(self, target: Session | None) -> None:
        if target is None:
            return
        if target.vault or target.has_script or target.script:
            self.with_master(lambda master: self._launch(target, master))
            return
        self.run_worker(self._add_tab(target))

    def _launch(self, target: Session, master: str | None) -> None:
        if target.has_script:
            target = replace(target, script=load_script(master, target.name))
        self.run_worker(self._add_tab(target))

    async def _add_tab(self, target: Session) -> None:
        self._tab_seq += 1
        pane_id = f"tab-{self._tab_seq}"
        tabs = self.query_one(TabbedContent)
        pane = TabPane(
            f"{target.user}@{target.host}" if target.user else target.host,
            Horizontal(SSHTerminal(target, self._master), classes="split"),
            id=pane_id,
        )
        await tabs.add_pane(pane)
        tabs.active = pane_id

    @on(TabbedContent.TabActivated)
    def _focus_tab(self) -> None:
        pane = self.query_one(TabbedContent).active_pane
        if pane is not None:
            for term in pane.query(SSHTerminal):
                term.focus()
                break

    async def action_close_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active:
            await tabs.remove_pane(tabs.active)

    def action_resources(self) -> None:
        term = self._focused_term()
        if term is None or term._conn is None:
            self.notify("Resources need an active SSH session", severity="warning")
            return
        self.push_screen(ResourcesScreen(term._conn))

    def action_plugin_command(self, index: int) -> None:
        _title, fn, _key = plugins.commands[index]
        fn(Context(self, self._focused_term()))

    def get_system_commands(self, screen):
        yield from super().get_system_commands(screen)
        for index, (title, _fn, _key) in enumerate(plugins.commands):
            yield SystemCommand(title, title, lambda index=index: self.action_plugin_command(index))

    def action_sftp(self) -> None:
        term = self._focused_term()
        if term is None or term._conn is None:
            self.notify("SFTP needs an active SSH session", severity="warning")
            return
        self.push_screen(SftpScreen(term._conn))

    async def action_split(self) -> None:
        pane = self.query_one(TabbedContent).active_pane
        if pane is None:
            return
        terms = list(pane.query(SSHTerminal))
        if not terms:
            return
        source = terms[0]
        term = SSHTerminal(source.target, source.master)
        await pane.query_one(".split").mount(term)
        term.focus()

    def action_rename(self) -> None:
        tabs = self.query_one(TabbedContent)
        pane_id = tabs.active
        if not pane_id:
            return
        self.push_screen(
            TextPrompt("Tab name", tabs.get_tab(pane_id).label_text), lambda name: self._rename(pane_id, name)
        )

    def _rename(self, pane_id: str, name: str | None) -> None:
        if not name or not name.strip():
            return
        self.query_one(TabbedContent).get_tab(pane_id).label = name.strip()

    def _focused_term(self) -> SSHTerminal | None:
        if isinstance(self.focused, SSHTerminal):
            return self.focused
        pane = self.query_one(TabbedContent).active_pane
        return next(iter(pane.query(SSHTerminal)), None) if pane is not None else None

    def action_search(self) -> None:
        term = self._focused_term()
        if term is not None:
            self.push_screen(TextPrompt("Search scrollback and screen"), lambda query: self._run_search(term, query))

    def _run_search(self, term: SSHTerminal, query: str | None) -> None:
        if not query:
            return
        count = term.search(query)
        self.notify(f"{count} match{'es' if count != 1 else ''}" if count else "no matches")

    def action_search_all(self) -> None:
        self.push_screen(TextPrompt("Search all open tabs"), self._run_search_all)

    def _run_search_all(self, query: str | None) -> None:
        if not query:
            return
        needle = query.lower()
        hits: list[tuple[str, SSHTerminal]] = []
        rows: list[str] = []
        tabs = self.query_one(TabbedContent)
        for pane in tabs.query(TabPane):
            label = tabs.get_tab(pane.id).label_text
            for term in pane.query(SSHTerminal):
                for line in term._screen_text().splitlines():
                    if needle in line.lower():
                        hits.append((pane.id, term))
                        rows.append(f"{label}  {line.strip()[:60]}")
        if not rows:
            self.notify("no matches in open tabs")
            return
        self.push_screen(SearchResults(rows), lambda index: self._jump_to_hit(hits, index, query))

    def _jump_to_hit(self, hits: list[tuple[str, SSHTerminal]], index: int | None, query: str) -> None:
        if index is None:
            return
        pane_id, term = hits[index]
        self.query_one(TabbedContent).active = pane_id
        term.search(query)
        term.focus()

    def action_search_next(self) -> None:
        term = self._focused_term()
        if term is not None:
            term.search_next()

    def action_broadcast(self) -> None:
        self.broadcast = not self.broadcast
        self.sub_title = "broadcast ON" if self.broadcast else ""

    def action_cycle_tab(self, step: int) -> None:
        tabs = self.query_one(TabbedContent)
        ids = [pane.id for pane in tabs.query(TabPane)]
        if ids and tabs.active in ids:
            tabs.active = ids[(ids.index(tabs.active) + step) % len(ids)]

    @on(SSHTerminal.HostKeyNeeded)
    def _ask_host_key(self, event: SSHTerminal.HostKeyNeeded) -> None:
        term, host, port, line, password = event.terminal, event.host, event.port, event.line, event.password
        screen = HostKeyScreen(host, port, event.fingerprint)
        self.push_screen(screen, lambda trust: term.resolve_host_key(trust, host, port, line, password))

    @on(SSHTerminal.AuthNeeded)
    def _ask_password(self, event: SSHTerminal.AuthNeeded) -> None:
        term = event.terminal
        label = f"Password for {term.target.user}@{term.target.host}"
        self.push_screen(PasswordPrompt(label), lambda pw: None if pw is None else term.connect(pw, typed=True))
