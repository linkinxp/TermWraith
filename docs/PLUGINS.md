# Plugins

Plugins add behaviour to termwraith without changing its code. A plugin can react to session events (connect, output, close) and add commands to the command palette, optionally with a key.

## Installing a plugin

Put a `.py` file in the plugins folder:

| Platform | Folder |
|---|---|
| Linux, macOS, Termux | `~/.config/termwraith/plugins/` |
| Windows | `%USERPROFILE%\.config\termwraith\plugins\` |

If the `TERMWRAITH_SESSIONS` environment variable is set, the folder is `plugins/` next to that file instead.

Plugins are loaded once, when termwraith starts. After adding, editing or removing a plugin, restart termwraith.

Plugins are loaded in alphabetical order by file name. Each plugin file must define a function named `register`:

```python
def register(api):
    ...
```

Plugins run with your full user rights. Install only plugins you trust, and read them before use.

## Errors

- If a file cannot be loaded (a syntax error, an exception at import time, or no `register` function), termwraith shows an error notification at startup naming the file. The other plugins still load.
- If a handler raises an exception while running, the error is ignored and the session continues. Handler errors are not reported, so test your handlers carefully.

## Events

Register event handlers on `api`. Each handler is called with the arguments listed below.

### `api.on_connect(fn)`

`fn(session)`

Called when a session's connection is established: after SSH authentication and port forwards, or after the telnet or serial connection opens. `session` is the session name as shown in the picker.

### `api.on_output(fn)`

`fn(session, text)`

Called each time output arrives from the remote end. `session` is the session name. `text` is the raw output decoded as UTF-8, including terminal escape sequences such as colours and cursor movement.

Output arrives in chunks, not lines. A chunk can end in the middle of a line, and in rare cases in the middle of a multi-byte character, which then appears as `�`. If you need whole lines, buffer the text yourself and split on newlines.

Only remote output triggers this event. Messages termwraith writes itself, such as `[termwraith] connecting to ...`, do not.

Output events fire only while at least one `on_output` handler is registered, so adding this handler has no cost otherwise.

### `api.on_close(fn)`

`fn(session)`

Called when a session's connection ends, before any automatic reconnect is scheduled. A session that reconnects fires `on_connect` again.

### Event example

```python
import datetime
import pathlib

LOG = pathlib.Path.home() / "termwraith-events.log"


def register(api):
    def stamp(event, session):
        with LOG.open("a") as f:
            f.write(f"{datetime.datetime.now().isoformat()} {event} {session}\n")

    api.on_connect(lambda session: stamp("connect", session))
    api.on_close(lambda session: stamp("close", session))
```

## Commands

### `api.command(title, fn, key=None)`

Adds a command.

- `title` is the text shown in the command palette (Ctrl+P).
- `fn(ctx)` is called when the command runs. `ctx` is described below.
- `key` is an optional key, written in Textual's key syntax, such as `"ctrl+k"`, `"f11"` or `"ctrl+alt+u"`.

A command runs when you pick it in the palette or press its key. Its key takes priority over the terminal, so the key is not typed into the session. Avoid keys that termwraith already uses (F2 to F10, Ctrl+B, Ctrl+F, Ctrl+PgUp and Ctrl+PgDn) and keys set as macros in Settings. Those keys may conflict or be ignored.

### The context object

`ctx` gives a command access to the session it was run from:

| Attribute or method | Description |
|---|---|
| `ctx.session` | Name of the focused session, or `None` if no session is focused. |
| `ctx.send(text)` | Types `text` into the focused session. Use `\r` for Enter. Does nothing if no session is focused. |
| `ctx.notify(message)` | Shows a short notification in the corner of the screen. |

### Command example

```python
def register(api):
    def uptime(ctx):
        ctx.send("uptime\r")

    def clear_screen(ctx):
        ctx.send("clear\r")

    api.command("Send uptime", uptime, key="ctrl+k")
    api.command("Clear screen", clear_screen)
```

## Full example

```python
# ~/.config/termwraith/plugins/ops.py
import datetime

DISK = "df -h / | tail -1\r"


def register(api):
    def disk(ctx):
        if ctx.session is None:
            ctx.notify("Focus a session first")
            return
        ctx.send(DISK)

    def mark(ctx):
        ctx.send(f"echo ---- {datetime.datetime.now():%H:%M} ----\r")

    api.command("Ops: disk usage", disk, key="f11")
    api.command("Ops: time marker", mark)
```

## Limits

- Plugins can register events and commands only. They cannot yet add menus, change the layout, read the screen contents or change settings.
- Plugins cannot be enabled or disabled from the interface. Remove or rename the file and restart.
- There is no API for plugins to talk to each other. Each plugin is loaded as its own module.

## Troubleshooting

- **Nothing happens:** check the file is in the plugins folder, ends in `.py`, defines `register(api)`, and that you restarted termwraith.
- **Error at startup:** the notification names the file and the problem. Fix the file and restart.
- **Command key does nothing:** check the key is not used by termwraith or a macro, and that the session is focused.
