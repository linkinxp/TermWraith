import asyncssh
from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

COMMAND = (
    "echo LOAD $(cat /proc/loadavg); echo CPU $(head -n 1 /proc/stat); "
    "echo UP $(cut -d' ' -f1 /proc/uptime); echo CORES $(nproc); echo HOST $(hostname); "
    "awk '/^(MemTotal|MemAvailable):/ {print \"MEM\", $1, $2}' /proc/meminfo; "
    "echo DISK $(df -P -B1 / | tail -n 1)"
)
GIB = 1024**3


def parse(text: str) -> dict:
    out: dict = {}
    mem: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(" ")
        parts = rest.split()
        try:
            if key == "LOAD":
                out["load"] = [float(x) for x in parts[:3]]
            elif key == "CPU":
                fields = [int(x) for x in parts[1:]]
                out["cpu"] = (fields[3] + fields[4], sum(fields))
            elif key == "UP":
                out["uptime"] = float(parts[0])
            elif key == "CORES":
                out["cores"] = int(parts[0])
            elif key == "HOST":
                out["host"] = rest.strip()
            elif key == "MEM":
                mem[parts[0].rstrip(":")] = int(parts[1]) * 1024
            elif key == "DISK":
                out["disk"] = (int(parts[1]), int(parts[2]), parts[5])
        except (ValueError, IndexError):
            continue
    out["mem_total"] = mem.get("MemTotal")
    out["mem_avail"] = mem.get("MemAvailable")
    return out


def cpu_percent(prev: tuple[int, int] | None, cur: tuple[int, int]) -> float | None:
    if prev is None:
        return None
    total = cur[1] - prev[1]
    if total <= 0:
        return 0.0
    return 100 * (1 - (cur[0] - prev[0]) / total)


def bar(pct: float, width: int = 30) -> Text:
    filled = round(max(0.0, min(pct, 100.0)) / 100 * width)
    return Text("[" + "#" * filled + "-" * (width - filled) + "]", style="#6A8759")


def uptime_text(seconds: float) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    return f"{days}d {hours}h {rest // 60}m"


class ResourcesScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close"), Binding("f4", "close", "Close")]

    def __init__(self, conn: asyncssh.SSHClientConnection) -> None:
        super().__init__()
        self._conn = conn
        self._prev_cpu: tuple[int, int] | None = None
        self._busy = False

    def compose(self):
        with Vertical(id="res-box"):
            yield Static("Reading remote resources ...", id="res-body")

    def on_mount(self) -> None:
        self.set_interval(2, self._poll)
        self.run_worker(self._poll(), exclusive=True, exit_on_error=False)

    async def _poll(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            result = await self._conn.run(COMMAND, check=False, timeout=5)
            data = parse(result.stdout or "")
        except (OSError, asyncssh.Error, TimeoutError) as exc:
            self.query_one("#res-body", Static).update(f"Remote resources unavailable: {exc}")
            return
        finally:
            self._busy = False
        self._show(data)

    def _show(self, data: dict) -> None:
        body = self.query_one("#res-body", Static)
        if "load" not in data:
            body.update("Resources need a Linux host (no /proc on this one).")
            return
        cpu = cpu_percent(self._prev_cpu, data["cpu"]) if "cpu" in data else None
        self._prev_cpu = data.get("cpu")
        lines = Text()
        lines.append(f"{data.get('host', '?')}  up {uptime_text(data.get('uptime', 0))}  {data.get('cores', '?')} cores\n\n")
        lines.append("CPU     ")
        lines.append_text(bar(cpu or 0))
        lines.append(f"  {cpu:.1f}%\n" if cpu is not None else "  measuring ...\n")
        load = data["load"]
        lines.append(f"Load    {load[0]:.2f}  {load[1]:.2f}  {load[2]:.2f}\n")
        total, avail = data.get("mem_total"), data.get("mem_avail")
        if total and avail is not None:
            used = total - avail
            lines.append("Memory  ")
            lines.append_text(bar(100 * used / total))
            lines.append(f"  {used / GIB:.1f} / {total / GIB:.1f} GiB\n")
        if "disk" in data:
            size, used, mount = data["disk"]
            lines.append(f"Disk {mount:<4}")
            lines.append_text(bar(100 * used / size if size else 0))
            lines.append(f"  {used / GIB:.1f} / {size / GIB:.1f} GiB\n")
        lines.append("\nF4 or Esc to close", style="dim")
        body.update(lines)

    def action_close(self) -> None:
        self.dismiss(None)
