#!/bin/sh
# Install or update termwraith (Linux and macOS). Re-run to update.
#   curl -fsSL https://raw.githubusercontent.com/linkinxp/TermWraith/main/install.sh | sh
set -eu

REPO="${TERMWRAITH_REPO:-https://github.com/linkinxp/TermWraith.git}"
SRC="${TERMWRAITH_HOME:-$HOME/.local/share/termwraith}"
BIN="${TERMWRAITH_BIN:-$HOME/.local/bin}"

command -v git >/dev/null 2>&1 || { echo "termwraith: git is required" >&2; exit 1; }
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "termwraith: python3 (3.10 or newer) is required" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "termwraith: python 3.10 or newer is required" >&2; exit 1; }

if [ -d "$SRC/.git" ]; then
    git -C "$SRC" pull --ff-only -q
else
    git clone -q "$REPO" "$SRC"
fi

"$PY" -m venv "$SRC/.venv" || { echo "termwraith: could not create a venv (on Debian/Ubuntu: sudo apt install python3-venv)" >&2; exit 1; }
"$SRC/.venv/bin/python" -m pip install -q --upgrade pip
"$SRC/.venv/bin/python" -m pip install -q "$SRC"

mkdir -p "$BIN"
printf '#!/bin/sh\nexec "%s/.venv/bin/termwraith" "$@"\n' "$SRC" > "$BIN/termwraith"
chmod +x "$BIN/termwraith"

echo "termwraith installed in $SRC"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Add $BIN to your PATH, e.g.: export PATH=\"$BIN:\$PATH\"" ;;
esac
echo "Run: termwraith"
