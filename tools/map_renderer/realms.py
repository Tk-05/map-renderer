"""Downloading Bedrock Realm worlds.

The Realms API calls and the Microsoft sign-in run in a small Node.js helper
(tools/realm_download, using prismarine-auth and prismarine-realms). This
module installs its packages on first use, calls it, and unpacks the
downloaded .mcworld into the project's .cache/ folder:

    .cache/realms/auth/                       sign-in tokens (keep private)
    .cache/realms/<realm id>/slot<N>/world/   the unpacked world
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import prompts
from .worlds import World, is_world, load_world

HELPER_DIR = Path(__file__).resolve().parent.parent / "realm_download"
HELPER = HELPER_DIR / "realms.js"
MIN_NODE = 18
EDITION = "Bedrock Realm"


class RealmError(Exception):
    pass


@dataclass(frozen=True)
class Realm:
    id: str
    name: str
    owner: str
    is_owner: bool
    state: str
    active_slot: int
    expired: bool

    @property
    def hint(self) -> str:
        parts = [f"id {self.id}", f"owner {self.owner}" if self.owner else ""]
        if self.expired:
            parts.append("expired")
        elif self.state and self.state.upper() != "OPEN":
            parts.append(self.state.lower())
        if not self.is_owner:
            parts.append("you are not the owner")
        return ", ".join(p for p in parts if p)


def auth_dir(cache_dir: Path) -> Path:
    return cache_dir / "realms" / "auth"


def world_dir(cache_dir: Path, realm_id: str, slot: int) -> Path:
    return cache_dir / "realms" / realm_id / f"slot{slot}" / "world"


# --------------------------------------------------------------------------
# Node.js helper
# --------------------------------------------------------------------------

def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise RealmError(f"Node.js {MIN_NODE} or newer is needed for Realm downloads: https://nodejs.org/")
    try:
        version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        major = int(version.lstrip("v").split(".")[0])
    except (OSError, ValueError):
        major = 0
    if major < MIN_NODE:
        raise RealmError(f"Node.js {MIN_NODE} or newer is needed for Realm downloads (found {version or '?'}).")
    return node


def _ensure_packages() -> None:
    if (HELPER_DIR / "node_modules" / "prismarine-realms").is_dir():
        return
    npm = shutil.which("npm")
    if not npm:
        raise RealmError("npm was not found. It comes with Node.js: https://nodejs.org/")
    prompts.info("Installing the Realm download helper (npm, once) ...")
    lock = (HELPER_DIR / "package-lock.json").is_file()
    cmd = [npm, "ci" if lock else "install", "--omit=dev", "--no-audit", "--no-fund"]
    if subprocess.run(cmd, cwd=HELPER_DIR).returncode != 0:
        raise RealmError(f"npm failed to install the Realm helper in {HELPER_DIR}")


def _client_version_args() -> list[str]:
    version = os.environ.get("REALMS_CLIENT_VERSION", "").strip()
    return ["--client-version", version] if version else []


def _run(command: str, cache_dir: Path, *args: str) -> object:
    """Run the helper. Sign-in prompts and progress go straight to the terminal."""
    node = _node()
    _ensure_packages()
    cmd = [node, str(HELPER), command, "--auth", str(auth_dir(cache_dir)), *_client_version_args(), *args]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RealmError(f"Realm {command} failed (see the message above).")
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise RealmError(f"Unexpected output from the Realm helper: {result.stdout[:200]!r}") from None


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def login(cache_dir: Path) -> None:
    _run("login", cache_dir)


def logout(cache_dir: Path) -> bool:
    folder = auth_dir(cache_dir)
    if not folder.exists():
        return False
    shutil.rmtree(folder)
    return True


def list_realms(cache_dir: Path) -> list[Realm]:
    data = _run("list", cache_dir)
    return [Realm(id=str(r["id"]), name=r.get("name") or f"Realm {r['id']}", owner=r.get("owner") or "",
                  is_owner=bool(r.get("isOwner")), state=r.get("state") or "",
                  active_slot=int(r.get("activeSlot") or 1), expired=bool(r.get("expired")))
            for r in data]  # type: ignore[union-attr]


def resolve_realm(cache_dir: Path, spec: str) -> Realm:
    """A Realm by id or name (exact, then case-insensitive)."""
    realms = list_realms(cache_dir)
    matches = [r for r in realms if spec in (r.id, r.name)] or [r for r in realms if r.name.lower() == spec.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        listing = "\n".join(f"  {r.id}  {r.name}" for r in matches)
        raise RealmError(f'Several Realms are named "{spec}". Pass the id instead:\n{listing}')
    if not realms:
        raise RealmError("This account has no Realms.")
    listing = "\n".join(f"  {r.id}  {r.name}" for r in realms)
    raise RealmError(f'Realm "{spec}" not found. Realms of this account:\n{listing}')


def download(cache_dir: Path, realm: Realm, slot: int | None = None) -> World:
    """Download the current state of a Realm world and unpack it; returns the world."""
    slot = slot or realm.active_slot
    target = world_dir(cache_dir, realm.id, slot)
    archive = target.parent / "world.mcworld"
    prompts.info(f'Downloading Realm "{realm.name}" (slot {slot}) ...')
    t = time.monotonic()
    result = _run("download", cache_dir, "--realm", realm.id, "--slot", str(slot), "--out", str(archive))
    size = int(result.get("size", 0)) if isinstance(result, dict) else archive.stat().st_size
    prompts.success(f"Downloaded {size / 1e6:.1f} MB in {round(time.monotonic() - t)}s")

    unpack(archive, target)
    archive.unlink(missing_ok=True)
    return load_world(target, EDITION)


def unpack(archive: Path, target: Path) -> None:
    """Unpack a .mcworld (zip) into `target`, replacing the previous copy only on success."""
    if not zipfile.is_zipfile(archive):
        raise RealmError(f"The downloaded file is not a .mcworld (zip) archive: {archive}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="unpack-", dir=target.parent))
    try:
        with zipfile.ZipFile(archive) as zf:
            root = staging.resolve()
            for info in zf.infolist():
                dest = (staging / info.filename).resolve()
                if not dest.is_relative_to(root):
                    raise RealmError(f"Unsafe path in the world archive: {info.filename}")
                zf.extract(info, staging)
                # Keep the archive's timestamps so renders can tell what changed.
                stamp = time.mktime((*info.date_time, 0, 0, -1))
                os.utime(dest, (stamp, stamp))

        world = staging if is_world(staging) else next(
            (d for d in staging.iterdir() if d.is_dir() and is_world(d)), None)
        if world is None:
            raise RealmError("The downloaded archive contains no world (level.dat missing).")

        old = target.with_name(target.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        world.rename(target)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
