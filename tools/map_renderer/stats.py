"""Map statistics from uNmINeD render logs, saved to map/stats.json.

uNmINeD prints world facts and render numbers to its log, e.g.

    (WebMapExport) World size: 35840 x 19968 blocks
    (WebMapExport) World region count: 303
    (WebMapExport) 50939 Chunks rendered

The total chunk count is only known after a render that drew every tile
(first render or --force); incremental renders keep the previous value.
The world seed is in the log too, but deliberately not stored: it would let
anyone locate every structure in the world.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_LINE = re.compile(r"\((\w+)\) (.*)$")

_PATTERNS: dict[str, re.Pattern[str]] = {
    "world_name": re.compile(r"^World name: (.*)$"),
    "world_type": re.compile(r"^World type: (.*)$"),
    "version": re.compile(r"^World last opened with version: (.*)$"),
    "size": re.compile(r"^World size: (\d+) x (\d+) blocks$"),
    "rect": re.compile(r"^World rectangle: rr\((-?\d+); (-?\d+); (\d+) x (\d+)\)$"),
    "regions": re.compile(r"^World region count: (\d+)$"),
    "terrain_tiles": re.compile(r"^(\d+) Terrain tiles$"),
    "terrain_skipped": re.compile(r"^(\d+) Terrain tiles skipped$"),
    "terrain_rendered": re.compile(r"^(\d+) Terrain tiles rendered$"),
    "chunks_rendered": re.compile(r"^(\d+) Chunks rendered$"),
    "chunks_failed": re.compile(r"^(\d+) Chunks failed$"),
    "speed": re.compile(r"^Elapsed time: [\d.:]+, (\d+) chunks/s$"),
    "zoomout_tiles": re.compile(r"^(\d+) Zoom-out tiles$"),
    "elapsed": re.compile(r"^Elapsed time total: ([\d.:]+)$"),
    "player": re.compile(r"^Found (?:local )?player data(?: (\S+))?$"),
}


def _seconds(text: str) -> int:
    """'0.00:01:24' (d.hh:mm:ss) -> 84"""
    days, _, clock = text.rpartition(".")
    h, m, s = (int(p) for p in clock.split(":"))
    return (int(days) if days else 0) * 86400 + h * 3600 + m * 60 + s


def parse_render_log(path: Path) -> dict:
    found: dict = {}
    players: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = _LINE.search(raw)
        if not line:
            continue
        # uNmINeD uses non-breaking spaces in some values, e.g. "rr(-59; -19; 70 x 39)".
        message = line.group(2).replace(" ", " ").strip()
        for key, pattern in _PATTERNS.items():
            m = pattern.match(message)
            if not m:
                continue
            if key == "player":
                players.add(m.group(1) or "local")
            else:
                found[key] = m.groups() if len(m.groups()) > 1 else m.group(1)
            break
    if players:
        found["players"] = len(players)
    return found


def tile_usage(dim_dir: Path) -> tuple[int, int]:
    files = size = 0
    tiles = dim_dir / "tiles"
    if tiles.is_dir():
        for f in tiles.rglob("*"):
            if f.is_file():
                files += 1
                size += f.stat().st_size
    return files, size


def update_stats(stats_file: Path, dim: str, log: dict, dim_dir: Path) -> dict:
    """Merge one dimension's render results into stats.json and return the document."""
    try:
        doc = json.loads(stats_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    doc.setdefault("dimensions", {})
    previous = doc["dimensions"].get(dim, {})

    world = doc.setdefault("world", {})
    if "world_name" in log:
        world["name"] = log["world_name"]
    if "world_type" in log:
        world["edition"] = log["world_type"]
    if "version" in log:
        world["version"] = log["version"]
    if "players" in log:
        world["players"] = log["players"]

    entry: dict = {"rendered": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if "size" in log:
        entry["size"] = [int(v) for v in log["size"]]
    if "rect" in log:
        rx, rz, rw, rh = (int(v) for v in log["rect"])
        entry["bounds"] = [rx * 512, rz * 512, (rx + rw) * 512 - 1, (rz + rh) * 512 - 1]
    if "regions" in log:
        entry["regions"] = int(log["regions"])
    if "terrain_tiles" in log:
        entry["terrainTiles"] = int(log["terrain_tiles"])
    if "zoomout_tiles" in log:
        entry["zoomOutTiles"] = int(log["zoomout_tiles"])

    rendered = int(log.get("terrain_rendered", 0))
    skipped = int(log.get("terrain_skipped", 0))
    chunks = int(log.get("chunks_rendered", 0))
    # Every tile was drawn -> this run saw every chunk.
    if rendered and not skipped:
        entry["chunks"] = chunks
    elif "chunks" in previous:
        entry["chunks"] = previous["chunks"]

    entry["lastRun"] = {
        "seconds": _seconds(log["elapsed"]) if "elapsed" in log else None,
        "tilesRendered": rendered,
        "chunksRendered": chunks,
        "chunksFailed": int(log.get("chunks_failed", 0)),
        "chunksPerSecond": int(log["speed"]) if "speed" in log else None,
        "full": bool(rendered and not skipped),
    }
    files, size = tile_usage(dim_dir)
    entry["disk"] = {"files": files, "bytes": size}

    doc["dimensions"][dim] = entry
    doc["generated"] = entry["rendered"]
    stats_file.parent.mkdir(parents=True, exist_ok=True)
    stats_file.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return doc
