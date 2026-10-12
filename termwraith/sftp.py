import posixpath
import stat
from pathlib import Path

import asyncssh
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList


class SftpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("backspace", "up", "Up")]

    def __init__(self, conn: asyncssh.SSHClientConnection) -> None:
        super().__init__()
        self._conn = conn
        self._sftp: asyncssh.SFTPClient | None = None
        self._path = "."
        self._entries: list[tuple[str, bool]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="sftp-box"):
            yield Label("SFTP", id="sftp-title")
            yield OptionList(id="sftp-list")
            with Horizontal(classes="buttons"):
                yield Button("Up", id="up")
                yield Button("Download", variant="success", id="get")
                yield Button("Upload", id="put")
                yield Button("Close", id="close")

    async def on_mount(self) -> None:
        try:
            self._sftp = await self._conn.start_sftp_client()
            await self.open_path(await self._sftp.realpath("."))
        except (OSError, asyncssh.Error) as exc:
            self.notify(f"SFTP failed: {exc}", severity="error")

    def on_unmount(self) -> None:
        if self._sftp is not None:
            self._sftp.exit()

    async def open_path(self, path: str) -> None:
        entries = []
        async for entry in self._sftp.scandir(path):
            if entry.filename in (".", ".."):
                continue
            entries.append((entry.filename, stat.S_ISDIR(entry.attrs.permissions or 0)))
        entries.sort(key=lambda e: (not e[1], e[0].lower()))
        self._path = path
        self._entries = entries
        self.query_one("#sftp-title", Label).update(f"SFTP  {path}")
        options = self.query_one("#sftp-list", OptionList)
        options.clear_options()
        options.add_options([f"{'/' if is_dir else ' '}{name}" for name, is_dir in entries])

    async def download(self, name: str, local_dir: Path | None = None) -> Path:
        target = (local_dir or Path.home() / "termwraith-downloads") / name
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._sftp.get(posixpath.join(self._path, name), str(target))
        return target

    async def upload(self, local: Path) -> str:
        remote = posixpath.join(self._path, local.name)
        await self._sftp.put(str(local), remote)
        await self.open_path(self._path)
        return remote

    @on(OptionList.OptionSelected, "#sftp-list")
    async def _selected(self, event: OptionList.OptionSelected) -> None:
        name, is_dir = self._entries[event.option_index]
        if is_dir:
            await self.open_path(posixpath.join(self._path, name))
        else:
            await self._download_named(name)

    async def _download_named(self, name: str) -> None:
        try:
            saved = await self.download(name)
            self.notify(f"saved {saved}")
        except (OSError, asyncssh.Error) as exc:
            self.notify(f"download failed: {exc}", severity="error")

    @on(Button.Pressed, "#up")
    async def _up_pressed(self) -> None:
        await self.action_up()

    async def action_up(self) -> None:
        parent = posixpath.dirname(posixpath.normpath(self._path)) or "/"
        await self.open_path(parent)

    @on(Button.Pressed, "#get")
    async def _get_pressed(self) -> None:
        index = self.query_one("#sftp-list", OptionList).highlighted
        if index is None:
            return
        name, is_dir = self._entries[index]
        if not is_dir:
            await self._download_named(name)

    @on(Button.Pressed, "#put")
    def _put_pressed(self) -> None:
        from .app import TextPrompt

        self.app.push_screen(TextPrompt("Local file to upload"), self._upload_from)

    async def _upload_from(self, local: str | None) -> None:
        if not local:
            return
        try:
            remote = await self.upload(Path(local).expanduser())
            self.notify(f"uploaded to {remote}")
        except (OSError, asyncssh.Error) as exc:
            self.notify(f"upload failed: {exc}", severity="error")

    @on(Button.Pressed, "#close")
    def _close_pressed(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
