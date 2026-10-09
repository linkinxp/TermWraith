from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Input, Label, Switch, TabbedContent, TabPane, Tree
from textual.widgets.tree import TreeNode

from textual.theme import Theme

from .store import Config, Session, load_config, load_sessions, parse_target, write_config, write_sessions
from .terminal import SSHTerminal

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


class SessionForm(ModalScreen[Session | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, session: Session | None = None, folder: str = "") -> None:
        super().__init__()
        self._session = session
        self._folder = folder

    def compose(self) -> ComposeResult:
        s = self._session
        with Vertical(id="box"):
            yield Label("Edit saved session" if s else "New saved session")
            yield Input(value=s.name if s else "", placeholder="name (optional)", id="name")
            yield Input(value=s.host if s else "", placeholder="host, e.g. 10.0.0.5", id="host")
            yield Input(value=s.user if s else "", placeholder="user", id="user")
            yield Input(value=str(s.port) if s else "22", placeholder="port", id="port")
            yield Input(
                value=(s.key or "") if s else "",
                placeholder="key file (optional, e.g. ~/.ssh/id_ed25519)",
                id="key",
            )
            yield Input(
                value=s.folder if s else self._folder,
                placeholder="folder, e.g. Clients/Acme (optional)",
                id="folder",
            )
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="success", id="save")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        host = self.query_one("#host", Input).value.strip()
        user = self.query_one("#user", Input).value.strip()
        port_text = self.query_one("#port", Input).value.strip() or "22"
        if not host or not user:
            self.notify("Host and user are required", severity="error")
            return
        if not port_text.isdigit() or not 0 < int(port_text) < 65536:
            self.notify("Port must be between 1 and 65535", severity="error")
            return
        name = self.query_one("#name", Input).value.strip() or f"{user}@{host}"
        key_text = self.query_one("#key", Input).value.strip()
        key = str(Path(key_text).expanduser()) if key_text else None
        folder = "/".join(part.strip() for part in self.query_one("#folder", Input).value.split("/") if part.strip())
        self.dismiss(Session(name=name, host=host, user=user, port=int(port_text), key=key, folder=folder))

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
            yield Label("Log directory")
            yield Input(value=self._config.log_dir, id="log-dir")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="success", id="save")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed, "#save")
    def _save(self) -> None:
        directory = self.query_one("#log-dir", Input).value.strip()
        if not directory:
            self.notify("Log directory is required", severity="error")
            return
        write_config(Config(log_enabled=self.query_one("#log-enabled", Switch).value, log_dir=directory))
        self.dismiss(None)

    @on(Button.Pressed, "#cancel")
    def _cancel_pressed(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Picker(ModalScreen[Session | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._sessions = load_sessions()

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label("Saved sessions")
            yield Tree("Saved sessions", id="saved")
            with Horizontal(classes="buttons"):
                yield Button("New", variant="primary", id="new")
                yield Button("Edit", id="edit")
                yield Button("Delete", variant="error", id="delete")
                yield Button("Settings", id="settings")
            yield Label("Quick connect  user@host[:port]")
            yield Input(placeholder="deploy@10.0.0.5:2222", id="quick")

    def on_mount(self) -> None:
        self._reload()

    def _reload(self) -> None:
        tree = self.query_one("#saved", Tree)
        tree.clear()
        tree.root.expand()
        folders: dict[str, TreeNode] = {"": tree.root}
        ordered = sorted(enumerate(self._sessions), key=lambda pair: (pair[1].folder.lower(), pair[1].name.lower()))
        for index, session in ordered:
            parent = self._folder_node(folders, session.folder)
            parent.add_leaf(f"{session.name}  ({session.user}@{session.host}:{session.port})", data=index)

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
        self._sessions.append(session)
        write_sessions(self._sessions)
        self._reload()

    @on(Button.Pressed, "#edit")
    def _edit(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        self.app.push_screen(SessionForm(self._sessions[index]), lambda session: self._replace(index, session))

    def _replace(self, index: int, session: Session | None) -> None:
        if session is None:
            return
        self._sessions[index] = session
        write_sessions(self._sessions)
        self._reload()

    @on(Button.Pressed, "#settings")
    def _settings(self) -> None:
        self.app.push_screen(SettingsScreen(load_config()))

    @on(Button.Pressed, "#delete")
    def _delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        del self._sessions[index]
        write_sessions(self._sessions)
        self._reload()

    @on(Input.Submitted)
    def _quick(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            return
        try:
            self.dismiss(parse_target(value))
        except ValueError:
            self.notify("Port must be a number", severity="error")

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


class TermWraith(App):
    TITLE = "termwraith"
    CSS = """
    #box {
        width: 64;
        height: auto;
        max-height: 90%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #saved { height: 12; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-right: 1; }
    .row { height: auto; }
    .row Label { padding: 1 0 0 1; }
    Picker, PasswordPrompt, HostKeyScreen, SessionForm, SettingsScreen { align: center middle; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0; }
    """
    BINDINGS = [
        Binding("f2", "connect", "Connect"),
        Binding("f3", "close_tab", "Close tab"),
        Binding("ctrl+pagedown", "cycle_tab(1)", "Next tab", show=False),
        Binding("ctrl+pageup", "cycle_tab(-1)", "Prev tab", show=False),
        Binding("f10", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._tab_seq = 0
        self.register_theme(DARCULA)
        self.theme = DARCULA.name

    def compose(self) -> ComposeResult:
        yield Header()
        yield TabbedContent()
        yield Footer()

    def on_mount(self) -> None:
        self.action_connect()

    def action_connect(self) -> None:
        self.push_screen(Picker(), self._open)

    def _open(self, target: Session | None) -> None:
        if target is not None:
            self.run_worker(self._add_tab(target))

    async def _add_tab(self, target: Session) -> None:
        self._tab_seq += 1
        pane_id = f"tab-{self._tab_seq}"
        tabs = self.query_one(TabbedContent)
        await tabs.add_pane(TabPane(f"{target.user}@{target.host}", SSHTerminal(target), id=pane_id))
        tabs.active = pane_id

    @on(TabbedContent.TabActivated)
    def _focus_tab(self) -> None:
        pane = self.query_one(TabbedContent).active_pane
        if pane is not None:
            for term in pane.query(SSHTerminal):
                term.focus()

    async def action_close_tab(self) -> None:
        tabs = self.query_one(TabbedContent)
        if tabs.active:
            await tabs.remove_pane(tabs.active)

    def action_cycle_tab(self, step: int) -> None:
        tabs = self.query_one(TabbedContent)
        ids = [pane.id for pane in tabs.query(TabPane)]
        if ids and tabs.active in ids:
            tabs.active = ids[(ids.index(tabs.active) + step) % len(ids)]

    @on(SSHTerminal.HostKeyNeeded)
    def _ask_host_key(self, event: SSHTerminal.HostKeyNeeded) -> None:
        term, line, password = event.terminal, event.line, event.password
        screen = HostKeyScreen(term.target.host, term.target.port, event.fingerprint)
        self.push_screen(screen, lambda trust: term.resolve_host_key(trust, line, password))

    @on(SSHTerminal.AuthNeeded)
    def _ask_password(self, event: SSHTerminal.AuthNeeded) -> None:
        term = event.terminal
        label = f"Password for {term.target.user}@{term.target.host}"
        self.push_screen(PasswordPrompt(label), lambda pw: None if pw is None else term.connect(pw))
