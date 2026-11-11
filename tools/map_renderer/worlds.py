"""Finding local Minecraft worlds (Bedrock, Bedrock Preview, Java)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class World:
    name: str
    path: Path
    edition: str          # "Bedrock", "Bedrock Preview", "Java"
    saved: datetime | None

    @property
    def saved_text(self) -> str:
        return self.saved.strftime("%d.%m.%Y %H:%M") if self.saved else "?"


def _roots() -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = []
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        for product, edition in (("Minecraft Bedrock", "Bedrock"), ("Minecraft Bedrock Preview", "Bedrock Preview")):
            users = Path(appdata) / product / "Users"
            if users.is_dir():
                roots += [(r, edition) for r in sorted(users.glob("*/games/com.mojang/minecraftWorlds"))]
        roots.append((Path(appdata) / ".minecraft" / "saves", "Java"))
    if localappdata:
        packages = Path(localappdata) / "Packages"
        roots.append((packages / "Microsoft.MinecraftUWP_8wekyb3d8bbwe/LocalState/games/com.mojang/minecraftWorlds",
                      "Bedrock"))
        roots.append((packages / "Microsoft.MinecraftWindowsBeta_8wekyb3d8bbwe/LocalState/games/com.mojang/minecraftWorlds",
                      "Bedrock Preview"))
    roots.append((Path.home() / ".minecraft" / "saves", "Java"))
    return [(r, e) for r, e in roots if r.is_dir()]


def _edition_of(path: Path) -> str:
    return "Bedrock" if (path / "db").is_dir() else "Java"


def _saved(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp((path / "level.dat").stat().st_mtime)
    except OSError:
        return None


def level_name(path: Path) -> str:
    name_file = path / "levelname.txt"
    if name_file.is_file():
        return name_file.read_text(encoding="utf-8", errors="replace").strip() or path.name
    return path.name


def load_world(path: Path, edition: str | None = None) -> World:
    return World(level_name(path), path, edition or _edition_of(path), _saved(path))


def is_world(path: Path) -> bool:
    return (path / "level.dat").is_file()


def find_worlds() -> list[World]:
    worlds: list[World] = []
    seen: set[Path] = set()
    for root, edition in _roots():
        for path in sorted(root.iterdir()):
            resolved = path.resolve()
            if resolved in seen or not is_world(path):
                continue
            seen.add(resolved)
            worlds.append(load_world(path, edition))
    worlds.sort(key=lambda w: w.saved or datetime.min, reverse=True)
    return worlds


def resolve_world(spec: str) -> World:
    """A world folder, or a world name / folder id from find_worlds()."""
    path = Path(spec).expanduser()
    if is_world(path):
        return load_world(path.resolve())

    worlds = find_worlds()
    matches = [w for w in worlds if spec in (w.name, w.path.name)]
    if not matches:
        matches = [w for w in worlds if w.name.lower() == spec.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        listing = "\n".join(f"  {w.path}" for w in matches)
        raise LookupError(f'Several worlds are named "{spec}". Pass the folder instead:\n{listing}')
    raise LookupError(f'World "{spec}" not found. Run "map-renderer worlds" or pass the world folder.')


def minecraft_running() -> bool:
    """Bedrock on Windows keeps the world open; reading it then can see half-saved data."""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return "minecraft.windows.exe" in out.lower()
