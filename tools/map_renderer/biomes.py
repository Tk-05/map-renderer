"""Biome maps: the world colored by biome instead of by block.

uNmINeD has no biome mode for web exports, but its stylesheet
(config/default/default.stylesheet.minecraft.js, JavaScript run by Jint) can
color blocks per biome: builder.style(...).color(...).biome("minecraft:desert").

So a second copy of the uNmINeD folder is kept next to the normal one, with a
patch appended to its stylesheet that colors every block by its biome, using
the Amidst/cubiomes biome colors uNmINeD ships with. The copy hard-links all
other files, so it costs almost no disk space. It is rebuilt whenever uNmINeD
is updated (uNmINeD may not be redistributed, so nothing of it is stored in
the repository).

The legend for the web page (name, color and group of each biome per
dimension) is written to map/biomes.json.
"""

from __future__ import annotations

import colorsys
import json
import os
import re
import shutil
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import bedrock, prompts
from .unmined import UnminedCli, UnminedError

# Dimensions that get a biome map (the End is a single biome).
DIMENSIONS = ("overworld", "nether")

STYLESHEET = Path("config/default/default.stylesheet.minecraft.js")
COLOR_FILES = {
    "bedrock": Path("config/default/cubiomes.biomecolors.bedrock.txt"),
    "java": Path("config/default/cubiomes.biomecolors.java.txt"),
}
MARKER = "// --- map-renderer: biome map ---"

# Readable names for Bedrock's internal (pre-1.18) biome ids.
BEDROCK_NAMES = {
    "hell": "Nether Wastes",
    "soulsand_valley": "Soul Sand Valley",
    "extreme_hills": "Windswept Hills",
    "extreme_hills_mutated": "Windswept Gravelly Hills",
    "extreme_hills_plus_trees": "Windswept Forest",
    "extreme_hills_plus_trees_mutated": "Windswept Forest (variant)",
    "extreme_hills_edge": "Mountain Edge",
    "roofed_forest": "Dark Forest",
    "roofed_forest_mutated": "Dark Forest Hills",
    "ice_plains": "Snowy Plains",
    "ice_plains_spikes": "Ice Spikes",
    "ice_mountains": "Snowy Mountains",
    "mesa": "Badlands",
    "mesa_bryce": "Eroded Badlands",
    "mesa_plateau": "Badlands Plateau",
    "mesa_plateau_mutated": "Modified Badlands Plateau",
    "mesa_plateau_stone": "Wooded Badlands",
    "mesa_plateau_stone_mutated": "Modified Wooded Badlands",
    "swampland": "Swamp",
    "swampland_mutated": "Swamp Hills",
    "mushroom_island": "Mushroom Fields",
    "mushroom_island_shore": "Mushroom Field Shore",
    "cold_beach": "Snowy Beach",
    "stone_beach": "Stony Shore",
    "cold_taiga": "Snowy Taiga",
    "cold_taiga_hills": "Snowy Taiga Hills",
    "cold_taiga_mutated": "Snowy Taiga Mountains",
    "mega_taiga": "Old Growth Pine Taiga",
    "mega_taiga_hills": "Giant Tree Taiga Hills",
    "redwood_taiga_mutated": "Old Growth Spruce Taiga",
    "redwood_taiga_hills_mutated": "Giant Spruce Taiga Hills",
    "birch_forest_mutated": "Old Growth Birch Forest",
    "birch_forest_hills_mutated": "Tall Birch Hills",
    "jungle_edge": "Sparse Jungle",
    "jungle_edge_mutated": "Modified Jungle Edge",
    "jungle_mutated": "Modified Jungle",
    "savanna_mutated": "Windswept Savanna",
    "savanna_plateau_mutated": "Shattered Savanna Plateau",
    "desert_mutated": "Desert Lakes",
    "taiga_mutated": "Taiga Mountains",
    "cherry_groves": "Cherry Grove",
    "legacy_frozen_ocean": "Legacy Frozen Ocean",
}


# Current names for the (older) section headings of uNmINeD's color files.
GROUP_NAMES = {"Extreme Hills": "Mountains", "Icy": "Snowy", "Mesa": "Badlands", "Mushroom": "Mushroom Fields"}


@dataclass(frozen=True)
class Biome:
    id: str        # e.g. "minecraft:desert"
    group: str     # section in uNmINeD's color file, e.g. "Desert"
    rgb: tuple[int, int, int]

    @property
    def hex(self) -> str:
        return "#%02x%02x%02x" % self.rgb

    def name(self, edition: str) -> str:
        short = self.id.split(":", 1)[-1]
        if edition == "bedrock" and short in BEDROCK_NAMES:
            return BEDROCK_NAMES[short]
        return short.replace("_mutated", "_variant").replace("_", " ").title()

    @property
    def dimension(self) -> str | None:
        if self.group == "Nether":
            return "nether"
        if self.group == "The End":
            return "end"
        if self.group == "None":
            return None
        return "overworld"


_COLOR = re.compile(r"^\s*([a-z0-9_.\-]+:[a-z0-9_./\-]+)\s*=\s*(?:rgb\((\d+),\s*(\d+),\s*(\d+)\)|#([0-9a-fA-F]{6}))")
_GROUP = re.compile(r"^#\s+([A-Z][\w ]*?)\s*$")


def read_colors(path: Path) -> list[Biome]:
    """Biomes from a uNmINeD cubiomes color file, with the section headings as groups."""
    biomes: list[Biome] = []
    group = "Other"
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if m := _GROUP.match(line):
            if not line.startswith(("# !", "# AMIDST", "# Most", "# License", "# Biome name")):
                group = m.group(1)
            continue
        if m := _COLOR.match(line):
            if m.group(5):
                h = m.group(5)
                rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            else:
                rgb = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
            biomes.append(Biome(m.group(1), group, rgb))
    return biomes


def edition_of(world_edition: str) -> str:
    return "java" if world_edition.lower().startswith("java") else "bedrock"


# --------------------------------------------------------------------------
# The biome copy of uNmINeD
# --------------------------------------------------------------------------

def _hsl(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return round(h * 360), round(s * 100), round(l * 100)


def _js_list(biomes: list[Biome]) -> str:
    return "[\n" + ",\n".join(f'        ["{b.id}", {", ".join(map(str, _hsl(b.rgb)))}]' for b in biomes) + "\n    ]"


def stylesheet_patch(root: Path) -> str:
    """JavaScript appended to the stylesheet: after the normal styles, every
    block gets the color of its biome (later styles win in uNmINeD)."""
    bedrock = read_colors(root / COLOR_FILES["bedrock"])
    java = read_colors(root / COLOR_FILES["java"])
    if not bedrock or not java:
        raise UnminedError("uNmINeD's biome color files are missing or empty; cannot build biome maps.")
    return f"""

{MARKER}
// Appended by map-renderer (tools/map_renderer/biomes.py). Colors every block
// by its biome (Amidst/cubiomes colors), keeping uNmINeD's height shading.
const MAP_RENDERER_BIOMES = {{
    bedrock: {_js_list(bedrock)},
    java: {_js_list(java)}
}};
const mapRendererBaseBuild = StyleSheet.prototype.build;
StyleSheet.prototype.build = function (builder) {{
    mapRendererBaseBuild.call(this, builder);
    const biomes = builder.isBedrock ? MAP_RENDERER_BIOMES.bedrock : MAP_RENDERER_BIOMES.java;
    for (const [name, h, s, l] of biomes) {{
        const id = "biome." + name.replace(":", ".");
        builder.color(id, h, s, l);
        builder.style("minecraft:*").color(id).biome(name)
            .useBiomeGrassColor(false).useBiomeFoliageColor(false).useBiomeWaterColor(false);
    }}
}};
"""


def _link_or_copy(src: str, dst: str) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def biome_cli(cli: UnminedCli, cache_dir: Path) -> UnminedCli:
    """The biome-coloring copy of `cli`, created or refreshed as needed."""
    source = cli.exe.parent
    target = cache_dir / "unmined-cli-biomes" / source.parent.name / source.name
    stamp = target / ".map-renderer-source"
    expected = f"{source}\n{cli.exe.stat().st_mtime_ns}\n"
    exe = target / cli.exe.name
    if exe.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8") == expected:
        return UnminedCli(exe)

    prompts.info("Preparing uNmINeD for biome maps ...")
    shutil.rmtree(target.parent, ignore_errors=True)  # also removes copies of older versions
    shutil.copytree(source, target, copy_function=_link_or_copy)

    # The stylesheet is replaced by a real file: writing to the hard link
    # would change the normal installation as well.
    sheet = target / STYLESHEET
    original = (source / STYLESHEET).read_text(encoding="utf-8-sig")
    if MARKER in original:
        raise UnminedError(f"{source / STYLESHEET} already contains the biome patch.")
    sheet.unlink()
    sheet.write_text(original + stylesheet_patch(source), encoding="utf-8")
    stamp.write_text(expected, encoding="utf-8")
    return UnminedCli(exe)


# --------------------------------------------------------------------------
# Biome lookup for hover/click on the web page (Bedrock worlds)
# --------------------------------------------------------------------------
#
# map/biomedata/<dim>/r.<rx>.<rz>.bin: one file per region (512x512 blocks),
# zlib-compressed, 128x128 bytes (one per 4x4 block cell, row by row along z).
# Byte = Bedrock biome number + 1; 0 = no data.
#
# map/biomedata/<dim>/o.<gx>.<gz>.bin: overview tiles of 32x32 regions at one
# byte per chunk (1024x1024, zlib), used by the page when zoomed far out
# instead of thousands of region files. Tiles are only written where there is
# data, so a few far-away chunks (e.g. from a long flight) cost one small file.
# index.json lists the regions and overview tiles that exist.

LOOKUP_DIR = "biomedata"
REGION_BLOCKS = 512
REGION_CELLS = REGION_BLOCKS // bedrock.CELL
CHUNKS_PER_REGION = REGION_BLOCKS // 16
OVERVIEW_CHUNKS = 32 * CHUNKS_PER_REGION  # overview tile: 32x32 regions, 1 byte per chunk

# Biome number -> byte value (number + 1); unknown -> 0.
_TO_VALUE = bytes([0 if b == bedrock.UNKNOWN else b + 1 for b in range(256)])


def write_lookup(map_dir: Path, world: Path, dims: list[str],
                 top_y: dict[str, int] | None = None) -> dict[str, Counter]:
    """Write the lookup files of `dims`; returns the cell count per biome number.
    `top_y`: per dimension the same --topY the map was rendered with."""
    chunks = bedrock.surface_biomes(world, dims, top_y)
    root = map_dir / LOOKUP_DIR
    counts: dict[str, Counter] = {}
    for dim in dims:
        regions: dict[tuple[int, int], bytearray] = {}
        tally: Counter = Counter()
        for (cx, cz), cells in chunks[dim].items():
            tally.update(cells)
            region = regions.get((cx // CHUNKS_PER_REGION, cz // CHUNKS_PER_REGION))
            if region is None:
                region = regions[(cx // CHUNKS_PER_REGION, cz // CHUNKS_PER_REGION)] = bytearray(REGION_CELLS ** 2)
            col = (cx % CHUNKS_PER_REGION) * bedrock.CELLS
            row = (cz % CHUNKS_PER_REGION) * bedrock.CELLS
            values = cells.translate(_TO_VALUE)
            for r in range(bedrock.CELLS):
                start = (row + r) * REGION_CELLS + col
                region[start:start + bedrock.CELLS] = values[r * bedrock.CELLS:(r + 1) * bedrock.CELLS]
        tally.pop(bedrock.UNKNOWN, None)
        counts[dim] = tally

        # Write into a fresh folder, then swap, so the page never sees half a set.
        target = root / dim
        staging = root / f"{dim}.new"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        for (rx, rz), data in regions.items():
            (staging / f"r.{rx}.{rz}.bin").write_bytes(zlib.compress(bytes(data), 9))

        # Overview tiles: one byte per chunk (its centre cell).
        tiles: dict[tuple[int, int], bytearray] = {}
        centre = (bedrock.CELLS // 2) * bedrock.CELLS + bedrock.CELLS // 2
        for (cx, cz), cells in chunks[dim].items():
            key = (cx // OVERVIEW_CHUNKS, cz // OVERVIEW_CHUNKS)
            tile = tiles.get(key)
            if tile is None:
                tile = tiles[key] = bytearray(OVERVIEW_CHUNKS ** 2)
            tile[(cz % OVERVIEW_CHUNKS) * OVERVIEW_CHUNKS + cx % OVERVIEW_CHUNKS] = _TO_VALUE[cells[centre]]
        for (gx, gz), data in tiles.items():
            (staging / f"o.{gx}.{gz}.bin").write_bytes(zlib.compress(bytes(data), 9))

        index = {
            "cell": bedrock.CELL,
            "region": REGION_BLOCKS,
            "regions": sorted([rx, rz] for rx, rz in regions),
            "overview": {"size": OVERVIEW_CHUNKS * 16, "pixels": OVERVIEW_CHUNKS,
                         "tiles": sorted([gx, gz] for gx, gz in tiles)},
        }
        (staging / "index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
        old = root / f"{dim}.old"
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        staging.rename(target)
        shutil.rmtree(old, ignore_errors=True)
    return counts


def biome_numbers(cli: UnminedCli) -> dict[int, str]:
    """Bedrock biome number -> id, from uNmINeD's vanilla.biomenumbers.bedrock.txt."""
    numbers: dict[int, str] = {}
    path = cli.exe.parent / "config" / "default" / "vanilla.biomenumbers.bedrock.txt"
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        number, sep, name = line.partition("=")
        if sep and number.strip().isdigit():
            numbers[int(number)] = name.strip()
    return numbers


# --------------------------------------------------------------------------
# Legend for the web page
# --------------------------------------------------------------------------

def write_legend(path: Path, cli: UnminedCli, edition: str, dims: list[str],
                 counts: dict[str, Counter] | None = None) -> dict:
    """Write biomes.json: the biomes of each dimension that has a biome map.

    With `counts` (Bedrock lookup data) only biomes that occur are listed, with
    their share of the explored area and the byte value used in the lookup
    files. Dimensions rendered earlier (and not part of this run) are kept.
    """
    biomes = read_colors(cli.exe.parent / COLOR_FILES[edition])
    by_id = {b.id: b for b in biomes}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("edition") != edition:
            doc = {}
    except (OSError, ValueError):
        doc = {}
    doc["edition"] = edition
    # Also used by the page as cache buster for the lookup files.
    doc["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries = doc.setdefault("dimensions", {})
    lookup = doc.setdefault("lookup", {})

    def entry(b: Biome) -> dict:
        return {"id": b.id, "name": b.name(edition), "group": GROUP_NAMES.get(b.group, b.group), "color": b.hex}

    numbers = biome_numbers(cli) if counts else {}
    order = {b.id: i for i, b in enumerate(biomes)}
    for dim in dims:
        tally = counts.get(dim) if counts else None
        if not tally:
            entries[dim] = [entry(b) for b in biomes if b.dimension == dim]
            lookup.pop(dim, None)
            continue
        total = sum(tally.values())
        rows = []
        for number, n in tally.items():
            biome_id = numbers.get(number, f"unknown:{number}")
            b = by_id.get(biome_id)
            if b:
                row = entry(b)
            else:  # newer than uNmINeD's color list: no color of its own
                known = not biome_id.startswith("unknown:")
                name = Biome(biome_id, "Other", (128, 128, 128)).name(edition) if known else f"Biome {number}"
                row = {"id": biome_id, "name": name, "group": "Other", "color": "#808080"}
            row["value"] = number + 1
            row["share"] = round(n / total, 5)
            rows.append(row)
        rows.sort(key=lambda r: (order.get(r["id"], len(order)), r["id"]))
        entries[dim] = rows
        lookup[dim] = f"{LOOKUP_DIR}/{dim}"
    if lookup:
        doc["lookupCell"] = bedrock.CELL
        doc["lookupRegion"] = REGION_BLOCKS
    else:
        doc.pop("lookup", None)
        doc.pop("lookupCell", None)
        doc.pop("lookupRegion", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return doc
