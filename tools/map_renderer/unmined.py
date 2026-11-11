"""Downloading and running the uNmINeD command line tool.

uNmINeD may not be redistributed, so it is always downloaded from
unmined.net into the project's .cache/ folder (git-ignored).
"""

from __future__ import annotations

import csv
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import prompts

DOWNLOAD_URL = "https://unmined.net/download/unmined-cli-{platform}-dev/"
USER_AGENT = "map-renderer/1.0"


class UnminedError(Exception):
    pass


@dataclass(frozen=True)
class UnminedCli:
    exe: Path

    @property
    def version(self) -> str:
        # Folder looks like "unmined-cli_0.20.11-dev_win-64bit".
        m = re.search(r"unmined-cli_([^_]+)", self.exe.parent.name)
        return m.group(1) if m else "unknown"


def platform_id() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    arm64 = machine in ("arm64", "aarch64")
    if system == "Windows":
        return "windows-arm64" if arm64 else "windows-64bit"
    if system == "Darwin":
        return "macos-arm64" if arm64 else "macos-intel"
    if system == "Linux":
        if machine.startswith("armv7"):
            return "linux-arm"
        musl = Path("/etc/alpine-release").exists()
        return ("linux-musl-" if musl else "linux-") + ("arm64" if arm64 else "x64")
    raise UnminedError(f"Unsupported platform: {system} {machine}")


def _install_dir(cache_dir: Path) -> Path:
    return cache_dir / "unmined-cli" / platform_id()


def installed(cache_dir: Path) -> UnminedCli | None:
    root = _install_dir(cache_dir)
    name = "unmined-cli.exe" if os.name == "nt" else "unmined-cli"
    hits = sorted(root.rglob(name)) if root.is_dir() else []
    return UnminedCli(hits[0]) if hits else None


def _download(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(target, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            out.write(chunk)
            done += len(chunk)
            if total and sys.stdout.isatty():
                print(f"\r  {done * 100 // total:3d}%  {done / 1e6:5.1f} / {total / 1e6:.1f} MB", end="", flush=True)
        if total and sys.stdout.isatty():
            print()


def _extract(archive: Path, dest: Path) -> None:
    magic = archive.read_bytes()[:2]
    if magic == b"PK":
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if not (dest / member).resolve().is_relative_to(dest.resolve()):
                    raise UnminedError(f"Unsafe path in archive: {member}")
            zf.extractall(dest)
    elif magic == b"\x1f\x8b":
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                target = (dest / member.name).resolve()
                if not target.is_relative_to(dest.resolve()) or member.islnk() or member.isdev():
                    raise UnminedError(f"Unsafe entry in archive: {member.name}")
            try:
                tf.extractall(dest, filter="data")
            except TypeError:  # Python < 3.12 without extraction filters (checked above)
                tf.extractall(dest)
    else:
        raise UnminedError("Unknown archive format (expected zip or tar.gz)")


def install(cache_dir: Path, force: bool = False) -> UnminedCli:
    root = _install_dir(cache_dir)
    if not force and (cli := installed(cache_dir)):
        return cli

    url = DOWNLOAD_URL.format(platform=platform_id())
    prompts.info(f"Downloading uNmINeD CLI from {url}")
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="unmined-", dir=root.parent))
    try:
        archive = staging / "download"
        _download(url, archive)
        unpacked = staging / "files"
        _extract(archive, unpacked)
        if root.exists():
            shutil.rmtree(root)
        unpacked.rename(root)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    cli = installed(cache_dir)
    if not cli:
        raise UnminedError(f"unmined-cli not found in the downloaded archive ({root})")
    if os.name != "nt":
        cli.exe.chmod(cli.exe.stat().st_mode | 0o111)
    prompts.success(f"uNmINeD CLI {cli.version} installed")
    return cli


_PROGRESS = re.compile(r"Rendering tile z(-?\d+) .*\[([\d.]+)%\]")
_ZOOM = re.compile(r"Rendering zoom level (-?\d+)")


def _follow_log(proc: subprocess.Popen, log_file: Path) -> None:
    """Show a one-line progress display from uNmINeD's log while it renders."""
    tty = sys.stdout.isatty()
    status, last_shown, pos = "Reading world", "", 0
    problems: list[str] = []

    def show(text: str) -> None:
        nonlocal last_shown
        if text == last_shown:
            return
        if tty:
            print(f"\r  {text:<60}", end="", flush=True)
        elif not text.endswith("%"):
            print(f"  {text}", flush=True)  # phases only, no percentage spam
        last_shown = text

    while True:
        finished = proc.poll() is not None
        if log_file.exists():
            with open(log_file, encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            for line in chunk.splitlines():
                if " ERR]" in line or " FTL]" in line or " WRN]" in line:
                    problems.append(line.split("] ", 1)[-1])
                if m := _ZOOM.search(line):
                    status = f"Zoom level {m.group(1)}"
                    show(status)
                elif m := _PROGRESS.search(line):
                    show(f"{status}  {float(m.group(2)):5.1f}%")
                elif "Scanning world" in line:
                    show("Reading world")
        if finished:
            break
        time.sleep(0.3)
    if tty and last_shown:
        print("\r" + " " * 64 + "\r", end="", flush=True)
    for p in problems[-5:]:
        prompts.warn(p)


def render(cli: UnminedCli, world: Path, dim: str, output: Path, *,
           zoomout: int, zoomin: int, force: bool, extra: list[str], log_file: Path) -> None:
    """Render one dimension. uNmINeD's full log is written to `log_file`."""
    output.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.unlink(missing_ok=True)
    cmd = [
        str(cli.exe), "web", "render",
        f"--world={world}",
        f"--dimension={dim}",
        f"--output={output}",
        "--imageformat=webp",
        f"--zoomout={zoomout}",
        f"--zoomin={zoomin}",
        "-c",  # continue on chunk errors
        f"--log-file={log_file}",
        "--log-console=false",
    ]
    if force:
        cmd.append("-f")
    cmd += extra
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL)
    try:
        _follow_log(proc, log_file)
    except KeyboardInterrupt:
        proc.terminate()
        raise
    if proc.returncode != 0:
        raise UnminedError(f"Rendering {dim} failed (exit code {proc.returncode}), log: {log_file}")


def blockfind(cli: UnminedCli, world: Path, dim: str, blocks: list[str]) -> list[dict[str, str]]:
    """All blocks matching `blocks` as rows with BLOCK, STATE, X, Y, Z."""
    with tempfile.TemporaryDirectory(prefix="map-renderer-scan-") as tmp:
        out = Path(tmp) / f"{dim}.csv"
        cmd = [
            str(cli.exe), "blockfind", "dump",
            f"--world={world}",
            f"--dimension={dim}",
            f"--block={','.join(blocks)}",
            "--csv-fields=block,state,x,y,z",
            f"--output={out}",
            "--log-level=warning",
            "-c",
        ]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            raise UnminedError(f"Scanning {dim} failed (exit code {result.returncode})")
        if not out.exists():
            return []
        with open(out, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))
