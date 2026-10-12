from textual.theme import Theme

# Colours from M4dGun/t-ui_themes (GPL-3.0). Order: background, foreground, primary, accent, secondary.
PALETTES = {
    "tui-dracula-v1": ("#282A36", "#FFFFFF", "#FF79C6", "#BD93F9", "#6272A4"),
    "tui-dracula-v2": ("#282A36", "#FFFFFF", "#FF79C6", "#BD93F9", "#6272A4"),
    "tui-nethunter-v1": ("#000000", "#00FF41", "#ADF0D3", "#FFFFFF", "#00FF41"),
    "tui-nethunter-v2": ("#000000", "#009F00", "#ADF0D3", "#00BB00", "#009900"),
    "tui-grid": ("#000000", "#DCDCDC", "#00FFFF", "#00FFFF", "#DCDCDC"),
    "tui-dev-2": ("#000000", "#AEEEEE", "#AEEEEE", "#CDCD00", "#00FF00"),
    "tui-dev-2-3": ("#000000", "#00C957", "#009ACD", "#FFC125", "#6E7B8B"),
    "tui-girls-frontline-ump45": ("#000000", "#E3B920", "#FCF7F0", "#E3B920", "#E3B920"),
    "tui-koban": ("#000000", "#00D6D6", "#46A37B", "#FF94C9", "#00FF00"),
    "tui-wallx": ("#282A36", "#FFFFFF", "#FF79C6", "#FF5555", "#8BE9FD"),
    "tui-tomboy-girl": ("#000000", "#FFD600", "#FFD600", "#FFFFFF", "#FFD600"),
    "tui-mellogram": ("#333333", "#0EC201", "#0EC201", "#4682B4", "#FFFFFF"),
}


def tui_themes() -> list[Theme]:
    return [
        Theme(
            name=name,
            primary=primary,
            secondary=secondary,
            accent=accent,
            foreground=foreground,
            background=background,
            dark=True,
        )
        for name, (background, foreground, primary, accent, secondary) in PALETTES.items()
    ]
