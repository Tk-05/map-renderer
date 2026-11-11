"""Command line interface.

    map-renderer                 interactive assistant
    map-renderer build           render the map and scan for structures
    map-renderer render          render the map only
    map-renderer scan            scan for structures only
    map-renderer worlds          list local Minecraft worlds
    map-renderer realm ACTION    Bedrock Realms: list, login, logout, download
    map-renderer update          download the latest uNmINeD CLI

build/render/scan take a local world (--world) or download a Realm first
(--realm). Options that are not given on the command line are asked for
interactively. Pass -y to use defaults instead (for scripts and scheduled tasks).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, prompts, realms, scan, stats, unmined
from .prompts import Aborted, Option, bold, cyan, dim
from .realms import Realm, RealmError
from .worlds import World, find_worlds, minecraft_running, resolve_world

DIMENSIONS = ("overworld", "nether", "end")
DIM_LABELS = {"overworld": "Overworld", "nether": "Nether", "end": "The End"}


class CliError(Exception):
    pass


# --------------------------------------------------------------------------
# Project
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Project:
    root: Path
    output: Path | None = None  # map folder outside the project (--output / MAP_RENDERER_OUTPUT)

    @property
    def map_dir(self) -> Path:
        return self.output or self.root / "map"

    @property
    def cache_dir(self) -> Path:
        return self.root / ".cache"

    @property
    def structures_file(self) -> Path:
        return self.map_dir / "structures.json"

    @property
    def stats_file(self) -> Path:
        return self.map_dir / "stats.json"

    def render_log(self, dim: str) -> Path:
        return self.cache_dir / "logs" / f"render-{dim}.log"

    @property
    def state_file(self) -> Path:
        return self.cache_dir / "map-renderer.json"

    def load_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _looks_like_project(path: Path) -> bool:
    return (path / "index.html").is_file() and ((path / "map").is_dir() or (path / "tools" / "map_renderer").is_dir())


def find_project(explicit: str | None, output: str | None = None) -> Project:
    output = output or os.environ.get("MAP_RENDERER_OUTPUT")
    out = Path(output).expanduser().resolve() if output else None
    # MAP_RENDERER_PROJECT is set in the renderer container, which has no index.html:
    # there only map/ and .cache/ (volumes) and tools/ are needed.
    explicit = explicit or os.environ.get("MAP_RENDERER_PROJECT")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / "index.html").is_file() and not (root / "tools" / "map_renderer").is_dir():
            raise CliError(f"{root} is not a map project (index.html missing).")
        return Project(root, out)
    for candidate in (Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[2]):
        if _looks_like_project(candidate):
            return Project(candidate, out)
    raise CliError("Map project not found (a folder with index.html and map/). Use --project.")


# --------------------------------------------------------------------------
# Plan: what to do, collected from options and prompts
# --------------------------------------------------------------------------

@dataclass
class Plan:
    world: World | None       # None until a Realm world has been downloaded
    render: bool
    scan: bool
    dims: list[str]
    realm: Realm | None = None
    slot: int | None = None    # Realm world slot; None = the active one
    force: bool = False
    extras: bool = False
    zoomin: int = 0
    zoomout: int = 6
    extra: list[str] = field(default_factory=list)

    @property
    def command(self) -> str:
        return "build" if self.render and self.scan else ("render" if self.render else "scan")

    def as_command_line(self, output: Path | None = None) -> str:
        parts = ["map-renderer", self.command]
        if self.realm:
            parts += ["--realm", _quote(self.realm.id)]
            if self.slot:
                parts += ["--slot", str(self.slot)]
        else:
            parts += ["--world", _quote(str(self.world.path))]
        if output:
            parts += ["--output", _quote(str(output))]
        if list(self.dims) != list(DIMENSIONS):
            parts += ["--dims", *self.dims]
        if self.render:
            if self.force:
                parts.append("--force")
            if self.zoomin != 0:
                parts += ["--zoomin", str(self.zoomin)]
            if self.zoomout != 6:
                parts += ["--zoomout", str(self.zoomout)]
        if self.scan and self.extras:
            parts.append("--extras")
        parts.append("-y")
        if self.render and self.extra:
            parts += ["--", *self.extra]
        return " ".join(parts)


def _quote(value: str) -> str:
    return f'"{value}"' if any(c in value for c in ' "\'&()') else value


_PATH, _REALM = "path", "realm"


def _ask_realm(project: Project) -> Realm:
    prompts.info("Loading your Realms ...")
    found = realms.list_realms(project.cache_dir)
    if not found:
        raise CliError("This account has no Realms.")
    last = project.load_state().get("realm")
    options = [Option(r, r.name, r.hint) for r in found]
    default = next((i for i, r in enumerate(found) if r.id == last), 0)
    return prompts.select("Which Realm? (only the owner can download the world)", options, default)


def _ask_world(project: Project) -> World | Realm:
    worlds = find_worlds()
    state = project.load_state()
    options = [Option(w, w.name, f"{w.edition:<15} saved {w.saved_text}") for w in worlds]
    options.append(Option(_PATH, f"Enter a folder path {prompts.SYM['ellipsis']}", key="p"))
    options.append(Option(_REALM, f"Download from a Realm {prompts.SYM['ellipsis']}", "needs Node.js", key="r"))
    if state.get("realm"):
        default = len(options) - 1
    else:
        default = next((i for i, w in enumerate(worlds) if str(w.path) == state.get("world")), 0)
    if not worlds:
        prompts.warn("No worlds found in the usual Minecraft folders.")
    while True:
        choice = prompts.select("Which world?", options, default)
        if choice == _REALM:
            return _ask_realm(project)
        if choice != _PATH:
            return choice
        path = prompts.text("World folder (contains level.dat)")
        try:
            return resolve_world(path)
        except LookupError as e:
            prompts.warn(str(e))


def build_plan(args: argparse.Namespace, project: Project, mode: str, interactive: bool) -> Plan:
    state = project.load_state()

    # World: a local folder, or a Realm that is downloaded when the plan runs
    world: World | None = None
    realm: Realm | None = None
    if args.world and args.realm:
        raise CliError("Use either --world or --realm, not both.")
    if args.world:
        try:
            world = resolve_world(args.world)
        except LookupError as e:
            raise CliError(str(e)) from None
    elif args.realm:
        realm = realms.resolve_realm(project.cache_dir, args.realm)
    elif interactive:
        choice = _ask_world(project)
        world, realm = (None, choice) if isinstance(choice, Realm) else (choice, None)
    else:
        raise CliError("No world given. Use --world (see: map-renderer worlds) or --realm (see: map-renderer realm list).")
    if args.slot and not realm:
        raise CliError("--slot only applies to --realm.")

    # Steps
    if mode == "ask" and interactive:
        do_render, do_scan = prompts.select("What should be done?", [
            Option((True, True), "Render map and scan for structures"),
            Option((True, False), "Render map only"),
            Option((False, True), "Scan for structures only", "portals, villages, strongholds, ..."),
        ])
    else:
        do_render, do_scan = mode in ("ask", "build", "render"), mode in ("ask", "build", "scan")

    # Dimensions
    if args.dims:
        dims = list(args.dims)
    elif interactive:
        last_dims = state.get("dims") or list(DIMENSIONS)
        dims = prompts.checkbox(
            "Which dimensions?",
            [Option(d, DIM_LABELS[d]) for d in DIMENSIONS],
            [i for i, d in enumerate(DIMENSIONS) if d in last_dims])
    else:
        dims = list(DIMENSIONS)
    dims = [d for d in DIMENSIONS if d in dims]

    plan = Plan(world, do_render, do_scan, dims, realm=realm, slot=args.slot)

    # Render options
    if do_render:
        plan.extra = list(args.extra)
        if args.force is not None:
            plan.force = args.force
        elif interactive:
            plan.force = prompts.confirm("Re-render everything? (otherwise only changed regions)", False)

        plan.zoomin = args.zoomin if args.zoomin is not None else 0
        plan.zoomout = args.zoomout if args.zoomout is not None else 6
        advanced_given = args.zoomin is not None or args.zoomout is not None or args.extra
        if interactive and not advanced_given and prompts.confirm("Change advanced render options?", False):
            plan.zoomin = prompts.integer(
                "Zoom-in levels with real tiles (each level needs ~4x the disk space)", 0, 0, 3)
            plan.zoomout = prompts.integer("Zoom-out levels", 6, 1, 10)
            extra = prompts.text("Extra uNmINeD arguments, e.g. --shadows=3d (empty = none)")
            plan.extra = shlex.split(extra, posix=False)

    # Scan options
    if do_scan:
        if args.extras is not None:
            plan.extras = args.extras
        elif interactive and ("overworld" in dims or "nether" in dims):
            plan.extras = prompts.confirm(
                "Also list very common finds? (spawners, mineshafts, amethyst geodes, nether fossils; "
                "tens of thousands in a big world)", False)

    return plan


def _summary(plan: Plan, project: Project) -> None:
    prompts.heading("Summary")
    steps = []
    if plan.render:
        steps.append("render" + (" (everything)" if plan.force else " (changed regions)"))
    if plan.scan:
        steps.append("scan structures" + (" incl. common finds" if plan.extras else ""))
    if plan.realm:
        slot = f"slot {plan.slot}" if plan.slot else f"active slot {plan.realm.active_slot}"
        print(f"  Realm       {plan.realm.name}  {dim(f'({slot}, downloaded first)')}")
    else:
        print(f"  World       {plan.world.name}  {dim(f'({plan.world.edition}, saved {plan.world.saved_text})')}")
    print(f"  Dimensions  {', '.join(DIM_LABELS[d] for d in plan.dims)}")
    print(f"  Steps       {', '.join(steps)}")
    if plan.render and (plan.zoomin or plan.zoomout != 6 or plan.extra):
        print(f"  Render      zoom-in {plan.zoomin}, zoom-out {plan.zoomout}"
              + (f", extra: {' '.join(plan.extra)}" if plan.extra else ""))
    print(f"  Output      {project.map_dir}")
    print(f"\n  {dim('Same run without questions:')}\n  {cyan(plan.as_command_line(project.output))}")


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def _duration(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def run_plan(plan: Plan, project: Project) -> None:
    started = time.monotonic()
    if plan.realm:
        prompts.heading(f"Downloading {plan.realm.name}")
        plan.world = realms.download(project.cache_dir, plan.realm, plan.slot)

    cli = unmined.install(project.cache_dir)
    prompts.info(f"uNmINeD CLI {cli.version}")

    if plan.render:
        for dim_id in plan.dims:
            prompts.heading(f"Rendering {DIM_LABELS[dim_id]}")
            t = time.monotonic()
            log_file = project.render_log(dim_id)
            unmined.render(cli, plan.world.path, dim_id, project.map_dir / dim_id,
                           zoomout=plan.zoomout, zoomin=plan.zoomin, force=plan.force, extra=plan.extra,
                           log_file=log_file)
            doc = stats.update_stats(project.stats_file, dim_id, stats.parse_render_log(log_file),
                                     project.map_dir / dim_id)
            d = doc["dimensions"][dim_id]
            run = d["lastRun"]
            details = f"{run['tilesRendered']:,} tiles / {run['chunksRendered']:,} chunks updated"
            if run["chunksFailed"]:
                details += f", {run['chunksFailed']:,} chunks failed"
            prompts.success(f"{DIM_LABELS[dim_id]} rendered in {_duration(time.monotonic() - t)} ({details})")
            prompts.info(dim(f"Full log: {log_file}"))

    if plan.scan:
        found: list[dict] = []
        for dim_id in plan.dims:
            prompts.heading(f"Scanning {DIM_LABELS[dim_id]}")
            kinds = scan.kinds_for(dim_id, plan.extras)
            prompts.info("Looking for " + ", ".join(k.label for k in kinds))
            t = time.monotonic()
            result = scan.scan_dimension(cli, plan.world.path, dim_id, plan.extras)
            counts = Counter(s["label"] for s in result)
            for kind in kinds:
                print(f"    {kind.label:<16} {counts.get(kind.label, 0):>6,}")
            prompts.success(f"{DIM_LABELS[dim_id]} scanned in {_duration(time.monotonic() - t)}")
            found += result
        merged = scan.write_structures(project.structures_file, plan.world.name, found, plan.dims)
        shown = project.structures_file
        if shown.is_relative_to(project.root):
            shown = shown.relative_to(project.root)
        prompts.success(f"{len(merged):,} structures saved to {shown}")

    prompts.heading(f"Done in {_duration(time.monotonic() - started)}.")
    if project.output:
        print(f"  Map written to {project.map_dir}. Serve it with the web container: "
              f"{cyan(f'MAP_DIR={_quote(str(project.map_dir))}')} (server/docker-compose.yml)")
    else:
        print(f"  Preview: {cyan(f'python -m http.server 8765 --directory {_quote(str(project.root))}')}"
              f"  then open http://localhost:8765")


def cmd_build(args: argparse.Namespace, mode: str) -> int:
    project = find_project(args.project, args.output)
    interactive = sys.stdin.isatty() and not args.yes

    if interactive:
        print(f"{bold('map-renderer')} {dim(__version__)}  {dim(prompts.SYM['dot'])}  project {project.root}")
        cli = unmined.installed(project.cache_dir)
        print(dim(f"uNmINeD CLI {cli.version}" if cli else "uNmINeD CLI not installed yet, will be downloaded"))

    plan = build_plan(args, project, mode, interactive)

    if not plan.realm and minecraft_running() and not args.ignore_running:
        message = "Minecraft is running. The world may not be fully saved."
        if not interactive:
            raise CliError(message + " Close it, or pass --ignore-running.")
        prompts.warn(message)
        if not prompts.confirm("Continue anyway?", False):
            raise Aborted()

    if interactive:
        _summary(plan, project)
        if not prompts.confirm("Start?", True):
            raise Aborted()

    source = {"realm": plan.realm.id} if plan.realm else {"world": str(plan.world.path)}
    project.save_state({**source, "dims": plan.dims})
    run_plan(plan, project)
    return 0


def cmd_realm(args: argparse.Namespace) -> int:
    project = find_project(args.project)
    if args.action == "login":
        realms.login(project.cache_dir)
        prompts.success(f"Signed in. Tokens are kept in {realms.auth_dir(project.cache_dir)}")
    elif args.action == "logout":
        removed = realms.logout(project.cache_dir)
        print("Signed out." if removed else "Not signed in.")
    elif args.action == "list":
        found = realms.list_realms(project.cache_dir)
        if not found:
            print("This account has no Realms.")
        width = max((len(r.name) for r in found), default=0)
        for r in found:
            print(f"{bold(r.name.ljust(width))}  {dim(r.hint)}")
    elif args.action == "download":
        if not args.realm:
            raise CliError("Which Realm? Use --realm NAME|ID (see: map-renderer realm list).")
        world = realms.download(project.cache_dir, realms.resolve_realm(project.cache_dir, args.realm), args.slot)
        prompts.success(f'"{world.name}" unpacked to {world.path}')
    return 0


def cmd_worlds(args: argparse.Namespace) -> int:
    worlds = find_worlds()
    if not worlds:
        print("No worlds found.")
        return 0
    width = max(len(w.name) for w in worlds)
    for w in worlds:
        print(f"{bold(w.name.ljust(width))}  {w.edition:<15}  saved {w.saved_text}")
        print(f"{'':{width}}  {dim(str(w.path))}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    project = find_project(args.project)
    before = unmined.installed(project.cache_dir)
    cli = unmined.install(project.cache_dir, force=True)
    if before and before.version == cli.version:
        print(f"Already the latest version ({cli.version}).")
    return 0


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

def make_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", metavar="DIR", help="map project folder (default: found automatically)")

    realm_opts = argparse.ArgumentParser(add_help=False)
    realm_opts.add_argument("--realm", metavar="NAME|ID",
                            help="download this Bedrock Realm's world first (needs Node.js; owner only)")
    realm_opts.add_argument("--slot", type=int, choices=(1, 2, 3),
                            help="Realm world slot (default: the active one)")

    run_opts = argparse.ArgumentParser(add_help=False, parents=[realm_opts])
    run_opts.add_argument("-w", "--world", help="world name, folder id or path")
    run_opts.add_argument("-o", "--output", metavar="DIR",
                          help="map folder to write to, e.g. one served by the web container "
                               "(default: map/ in the project, or MAP_RENDERER_OUTPUT)")
    run_opts.add_argument("-d", "--dims", nargs="+", choices=DIMENSIONS, metavar="DIM",
                          help="dimensions: overworld nether end (default: all)")
    run_opts.add_argument("-y", "--yes", action="store_true",
                          help="don't ask, use defaults for everything not given")
    run_opts.add_argument("--ignore-running", action="store_true",
                          help="continue even if Minecraft is running")

    render_opts = argparse.ArgumentParser(add_help=False)
    group = render_opts.add_argument_group("render options")
    group.add_argument("--force", action=argparse.BooleanOptionalAction, default=None,
                       help="re-render all regions, not just changed ones")
    group.add_argument("--zoomin", type=int, help="zoom-in levels with real tiles (default: 0)")
    group.add_argument("--zoomout", type=int, help="zoom-out levels (default: 6)")

    scan_opts = argparse.ArgumentParser(add_help=False)
    group = scan_opts.add_argument_group("scan options")
    group.add_argument("--extras", "--spawners", dest="extras", action=argparse.BooleanOptionalAction, default=None,
                       help="also list very common finds: spawners, mineshafts, amethyst geodes, nether fossils")

    parser = argparse.ArgumentParser(
        prog="map-renderer", parents=[common],
        description="Render the Minecraft web map with uNmINeD and scan the world for structures.",
        epilog="Run without a command for the interactive assistant. "
               "Extra uNmINeD render arguments go after --, e.g.: map-renderer render -- --shadows=3d")
    parser.add_argument("--version", action="version", version=f"map-renderer {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("build", parents=[common, run_opts, render_opts, scan_opts],
                   help="render the map and scan for structures")
    sub.add_parser("render", parents=[common, run_opts, render_opts], help="render the map only")
    sub.add_parser("scan", parents=[common, run_opts, scan_opts], help="scan for structures only")
    sub.add_parser("worlds", parents=[common], help="list local Minecraft worlds")
    realm = sub.add_parser(
        "realm", parents=[common, realm_opts], help="Bedrock Realms: list, login, logout, download",
        description="Sign in with Microsoft and download Bedrock Realm worlds. Needs Node.js 18+. "
                    "Only the Realm owner can download the world. Set REALMS_CLIENT_VERSION "
                    "(e.g. 1.26.30) if the Realms API asks for a newer client.")
    realm.add_argument("action", choices=("list", "login", "logout", "download"),
                       help="list: your Realms; login/logout: Microsoft sign-in; "
                            "download: fetch and unpack a world (--realm, --slot)")
    sub.add_parser("update", parents=[common], help="download the latest uNmINeD CLI")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]

    prompts.setup_terminal()
    parser = make_parser()
    args = parser.parse_args(argv)

    # Fill in options a subcommand doesn't define (e.g. scan has no --force).
    for name, default in (("world", None), ("output", None), ("realm", None), ("slot", None), ("dims", None), ("yes", False),
                          ("ignore_running", False), ("force", None), ("zoomin", None), ("zoomout", None),
                          ("extras", None)):
        if not hasattr(args, name):
            setattr(args, name, default)
    args.extra = extra

    try:
        if args.command is None:
            if not sys.stdin.isatty():
                parser.print_help()
                return 2
            return cmd_build(args, "ask")
        if args.command in ("build", "render", "scan"):
            return cmd_build(args, args.command)
        if args.command == "worlds":
            return cmd_worlds(args)
        if args.command == "realm":
            return cmd_realm(args)
        if args.command == "update":
            return cmd_update(args)
    except Aborted:
        print(dim("Aborted."))
        return 130
    except KeyboardInterrupt:
        print(dim("\nInterrupted. Run the same command again to continue where it stopped."))
        return 130
    except (CliError, unmined.UnminedError, RealmError) as e:
        print(f"{prompts.red('error:')} {e}", file=sys.stderr)
        return 1
    return 0
