"""Finding structures in a world through characteristic blocks.

Each structure type is recognised by blocks that (almost) only generate there,
e.g. bells for villages, or by a combination of blocks, e.g. a cauldron, a
flower pot and a crafting table close together for a swamp hut. Matching
blocks are grouped by single-linkage clustering: blocks closer than `gap`
(Chebyshev distance) are one structure.

The rules were tuned on a large Bedrock world (see the comments). Structures
without any distinctive block, like shipwrecks and pillager outposts, can't
be found this way.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

from .unmined import UnminedCli, blockfind


@dataclass(frozen=True)
class Kind:
    id: str
    label: str
    blocks: tuple[str, ...]   # block names, "*" wildcards allowed; "name|state-text" also filters by state
    gap: int                  # clustering distance in blocks
    min_blocks: int = 1       # drop smaller clusters (player-placed noise)
    max_blocks: int | None = None              # drop bigger clusters (e.g. player bases)
    requires: tuple[tuple[str, ...], ...] = ()  # each group: at least one of these blocks in the cluster
    forbids: tuple[str, ...] = ()               # none of these blocks may be in the cluster
    min_y: int | None = None                    # bounds for the cluster centre
    max_y: int | None = None
    not_near: tuple[str, int] | None = None     # (kind id found earlier in this dimension, radius)
    optional: bool = False                      # very common: only with --extras


def _b(*names: str) -> tuple[str, ...]:
    return tuple(f"minecraft:{n}" for n in names)


NETHER_PORTAL = Kind("nether_portal", "Nether Portal", _b("portal"), gap=1)
SPAWNER = Kind("spawner", "Spawner", _b("mob_spawner"), gap=8)

STRUCTURES: dict[str, tuple[Kind, ...]] = {
    "overworld": (
        NETHER_PORTAL,
        Kind("stronghold", "Stronghold", _b("end_portal_frame"), gap=16),
        Kind("village", "Village", _b("bell"), gap=96),
        Kind("trial_chamber", "Trial Chamber", _b("trial_spawner", "vault"), gap=48),
        Kind("ancient_city", "Ancient City", _b("reinforced_deepslate"), gap=64, min_blocks=20),
        Kind("ocean_monument", "Ocean Monument", _b("wet_sponge", "sponge|sponge_type:wet"), gap=48, min_blocks=5),
        # One blue terracotta in the floor, TNT trap and chiseled sandstone below.
        Kind("desert_pyramid", "Desert Pyramid", _b("blue_terracotta", "tnt", "chiseled_sandstone"), gap=20,
             requires=(_b("blue_terracotta"), _b("tnt", "chiseled_sandstone"))),
        # Arrow trap: tripwire hooks + dispensers. Underground matches are trial chambers.
        Kind("jungle_temple", "Jungle Temple", _b("tripwire_hook", "dispenser"), gap=16,
             requires=(_b("tripwire_hook"), _b("dispenser")), min_y=55),
        # Exactly one cauldron, flower pot and crafting table; bigger groups are player builds.
        Kind("swamp_hut", "Swamp Hut", _b("cauldron", "flower_pot", "crafting_table"), gap=6,
             requires=(_b("cauldron"), _b("flower_pot"), _b("crafting_table")), max_blocks=4),
        # Older chunks store carpet as "carpet" with a colour state.
        Kind("igloo", "Igloo", _b("white_carpet", "carpet|color:white", "bed", "furnace", "crafting_table"), gap=5,
             requires=(_b("white_carpet", "carpet|color:white"), _b("bed"), _b("furnace")), max_blocks=20),
        # Mansions have 12,000-17,000 dark oak planks.
        Kind("woodland_mansion", "Woodland Mansion", _b("dark_oak_planks"), gap=4, min_blocks=10000),
        Kind("ruined_portal", "Ruined Portal", _b("crying_obsidian"), gap=12),
        Kind("trail_ruins", "Trail Ruins", _b("suspicious_gravel", "*_glazed_terracotta"), gap=24,
             requires=(_b("suspicious_gravel"), _b("*_glazed_terracotta"))),
        # Suspicious gravel/sand under water; pyramids and trail ruins have it too.
        Kind("ocean_ruins", "Ocean Ruins", _b("suspicious_gravel", "suspicious_sand", "*_glazed_terracotta"), gap=24,
             requires=(_b("suspicious_gravel", "suspicious_sand"),), forbids=_b("*_glazed_terracotta"),
             min_y=20, max_y=61, not_near=("desert_pyramid", 48)),
        # Very common, opt-in:
        Kind("mineshaft", "Mineshaft", _b("rail", "web"), gap=16, requires=(_b("rail"), _b("web")), optional=True),
        Kind("amethyst_geode", "Amethyst Geode", _b("budding_amethyst"), gap=8, optional=True),
        replace(SPAWNER, optional=True),
    ),
    "nether": (
        NETHER_PORTAL,
        Kind("fortress", "Nether Fortress", _b("nether_brick_fence"), gap=48, min_blocks=30),
        Kind("bastion", "Bastion Remnant", _b("gilded_blackstone"), gap=48, min_blocks=10),
        Kind("ruined_portal", "Ruined Portal", _b("crying_obsidian"), gap=12, not_near=("bastion", 64)),
        SPAWNER,
        Kind("nether_fossil", "Nether Fossil", _b("bone_block"), gap=3, min_blocks=5, optional=True),
    ),
    "end": (
        Kind("end_gateway", "End Gateway", _b("end_gateway"), gap=3),
        # Separate cities are >100 blocks apart; 48 keeps towers, bridges and ship together.
        Kind("end_city", "End City", _b("purpur_block", "purpur_pillar", "purpur_stairs", "end_rod"), gap=48,
             min_blocks=300),
        Kind("end_ship", "End Ship", _b("skull", "dragon_head"), gap=24),
        Kind("exit_portal", "Exit Portal", _b("end_portal"), gap=8),
    ),
}

# How far the game looks for an existing portal on the other side.
PORTAL_SEARCH_RADIUS = {"overworld": 128, "nether": 16}

Point = tuple[int, int, int, str, str]  # x, y, z, block, block state


def kinds_for(dim: str, with_optional: bool) -> tuple[Kind, ...]:
    return tuple(k for k in STRUCTURES[dim] if with_optional or not k.optional)


def _spec_matches(spec: str, block: str, state: str) -> bool:
    name, _, state_filter = spec.partition("|")
    return fnmatchcase(block, name) and (not state_filter or state_filter in state)


def _query_patterns(kinds: tuple[Kind, ...]) -> list[str]:
    """Block expressions for uNmINeD's blockfind (wildcards without namespace)."""
    patterns = set()
    for kind in kinds:
        for spec in kind.blocks:
            name = spec.partition("|")[0]
            patterns.add(name.removeprefix("minecraft:") if "*" in name else name)
    return sorted(patterns)


@dataclass
class Cluster:
    kind: Kind
    points: list[Point] = field(default_factory=list)

    def center(self) -> tuple[int, int, int]:
        n = len(self.points)
        return (round(sum(p[0] for p in self.points) / n),
                round(sum(p[1] for p in self.points) / n),
                round(sum(p[2] for p in self.points) / n))

    def bbox(self) -> list[int]:
        xs, ys, zs = zip(*((p[0], p[1], p[2]) for p in self.points))
        return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


def _accepts(kind: Kind, cluster: Cluster, found_so_far: dict[str, list[tuple[int, int]]]) -> bool:
    n = len(cluster.points)
    if n < kind.min_blocks or (kind.max_blocks is not None and n > kind.max_blocks):
        return False
    blocks = {(p[3], p[4]) for p in cluster.points}
    if any(not any(_spec_matches(spec, b, s) for b, s in blocks for spec in group) for group in kind.requires):
        return False
    if any(_spec_matches(spec, b, s) for b, s in blocks for spec in kind.forbids):
        return False
    x, y, z = cluster.center()
    if (kind.min_y is not None and y < kind.min_y) or (kind.max_y is not None and y > kind.max_y):
        return False
    if kind.not_near:
        other, radius = kind.not_near
        if any(abs(x - ox) <= radius and abs(z - oz) <= radius for ox, oz in found_so_far.get(other, ())):
            return False
    return True


def cluster_points(kind: Kind, points: list[Point]) -> list[Cluster]:
    gap = kind.gap
    parent = list(range(len(points)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    def linked(a: list[int], b: list[int]) -> bool:
        for i in a:
            xi, yi, zi = points[i][:3]
            for j in b:
                xj, yj, zj = points[j][:3]
                if max(abs(xi - xj), abs(yi - yj), abs(zi - zj)) <= gap:
                    return True
        return False

    # Cells of edge `gap`: points sharing a cell are always within `gap`.
    grid: dict[tuple[int, int, int], list[int]] = {}
    for i, p in enumerate(points):
        grid.setdefault((p[0] // gap, p[1] // gap, p[2] // gap), []).append(i)
    for members in grid.values():
        for j in members[1:]:
            union(members[0], j)

    # Neighbouring cells: join on the first pair within `gap`.
    half = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
            if (dx, dy, dz) > (0, 0, 0)]
    for (cx, cy, cz), members in grid.items():
        for dx, dy, dz in half:
            other = grid.get((cx + dx, cy + dy, cz + dz))
            if other and find(members[0]) != find(other[0]) and linked(members, other):
                union(members[0], other[0])

    groups: dict[int, Cluster] = {}
    for i, p in enumerate(points):
        groups.setdefault(find(i), Cluster(kind)).points.append(p)
    return list(groups.values())


def _describe(dim: str, cluster: Cluster, index: int) -> dict:
    kind = cluster.kind
    x, y, z = cluster.center()
    entry = {
        "id": f"{dim}:{kind.id}:{index}",
        "dim": dim,
        "type": kind.id,
        "label": kind.label,
        "x": x, "y": y, "z": z,
        "blocks": len(cluster.points),
    }
    states = [p[4] for p in cluster.points]
    if kind.id == "nether_portal":
        entry["axis"] = "x" if any("portal_axis:x" in s for s in states) else "z"
        entry["bbox"] = cluster.bbox()
    elif kind.id == "stronghold":
        entry["eyes"] = sum("end_portal_eye_bit:1" in s for s in states)
    return entry


def scan_dimension(cli: UnminedCli, world: Path, dim: str, with_optional: bool) -> list[dict]:
    kinds = kinds_for(dim, with_optional)
    rows = blockfind(cli, world, dim, _query_patterns(kinds))
    return find_structures(dim, kinds, rows)


def find_structures(dim: str, kinds: tuple[Kind, ...], rows: list[dict[str, str]]) -> list[dict]:
    """Structures from blockfind rows (BLOCK, STATE, X, Y, Z). A block can count for several kinds."""
    by_block: dict[tuple[str, str], list[Point]] = {}
    for row in rows:
        block, state = row["BLOCK"], row.get("STATE", "")
        by_block.setdefault((block, state), []).append((int(row["X"]), int(row["Y"]), int(row["Z"]), block, state))

    found: list[dict] = []
    centres: dict[str, list[tuple[int, int]]] = {}
    for kind in kinds:
        points = [p for (block, state), pts in by_block.items()
                  if any(_spec_matches(spec, block, state) for spec in kind.blocks) for p in pts]
        clusters = [c for c in cluster_points(kind, points) if _accepts(kind, c, centres)]
        clusters.sort(key=lambda c: c.center())
        centres[kind.id] = [(c.center()[0], c.center()[2]) for c in clusters]
        found += [_describe(dim, c, i + 1) for i, c in enumerate(clusters)]
    return found


def link_portals(structures: list[dict]) -> None:
    """Predict where each Overworld/Nether portal leads (x/8 rule)."""
    portals = {d: [s for s in structures if s["type"] == "nether_portal" and s["dim"] == d]
               for d in ("overworld", "nether")}
    for src, dst, factor in (("overworld", "nether", 1 / 8), ("nether", "overworld", 8)):
        radius = PORTAL_SEARCH_RADIUS[dst]
        for p in portals[src]:
            tx, tz = math.floor(p["x"] * factor), math.floor(p["z"] * factor)
            p["target"] = {"dim": dst, "x": tx, "z": tz}
            best, best_d = None, math.inf
            for q in portals[dst]:
                if abs(q["x"] - tx) > radius or abs(q["z"] - tz) > radius:
                    continue
                d = math.dist((q["x"], q["y"], q["z"]), (tx, p["y"], tz))
                if d < best_d:
                    best, best_d = q, d
            p["link"] = best["id"] if best else None


def write_structures(path: Path, world_name: str, structures: list[dict], dims: list[str]) -> list[dict]:
    """Merge with results of dimensions that were not rescanned and save."""
    previous: list[dict] = []
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8")).get("structures", [])
        except (ValueError, OSError):
            previous = []
    merged = [s for s in previous if s["dim"] not in dims] + structures
    link_portals(merged)
    doc = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "world": world_name,
        "structures": merged,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return merged
