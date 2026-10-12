# termwraith

A SecureCRT-style terminal for SSH, telnet and serial, built on Textual.

## Install

Linux and macOS (needs git and Python 3.10+):

    curl -fsSL https://raw.githubusercontent.com/linkinxp/TermWraith/main/install.sh | sh

Windows (PowerShell, needs git and Python 3.10+):

    irm https://raw.githubusercontent.com/linkinxp/TermWraith/main/install.ps1 | iex

## Android (Termux)

Install Termux from F-Droid (the Play Store build is outdated), then run the same Linux command inside Termux. The installer uses `pkg` to add git and Python. Termux has no F-keys on its extra-keys bar by default, so use the Termux extra-keys row to send F2 to F10 when you need them.

## Update

Run the same install command again. It pulls the latest code and reinstalls.

## Run

    termwraith

## Import from SecureCRT

In the session picker, press Import and give a path to either:

- the SecureCRT `Sessions` folder (`%APPDATA%\VanDyke\Config\Sessions`), or one of its `.ini` files
- a `.reg` export of `HKEY_CURRENT_USER\Software\VanDyke\SecureCRT\Sessions`

Folders, hosts, ports, usernames, key paths, serial ports and baud rates are imported; the `Default` session fills in missing values. Saved passwords are encrypted by SecureCRT and are not imported; re-enter them in termwraith.

## Keys

- F2 connect, F3 close tab, F4 remote resources (SSH), F6 split pane, F7 rename tab
- F8 next search match, Ctrl+F search, Ctrl+B broadcast to all panes
- Forwards: L:local:host:remote, R:remote:host:local, D:port (SOCKS5 proxy, SSH)
- F9 SFTP browser (SSH), Ctrl+PgUp/PgDn cycle tabs, Shift+PgUp/PgDn scroll, F10 quit
