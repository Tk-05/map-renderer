"""Interactive prompts and terminal output (standard library only)."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence


class Aborted(Exception):
    """The user cancelled a prompt (Ctrl+C / Ctrl+D)."""


# --------------------------------------------------------------------------
# Colors
# --------------------------------------------------------------------------

_color = False

# Symbols, with ASCII fallbacks for consoles that can't show them (e.g. cp1252 pipes).
SYM = {"ok": "✔", "warn": "!", "pointer": "›", "dot": "·", "ellipsis": "…"}
_ASCII = {"ok": "OK", "warn": "!", "pointer": ">", "dot": "-", "ellipsis": "..."}


def setup_terminal() -> None:
    global _color
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # never crash on an unprintable character
        except (AttributeError, ValueError):
            pass
    try:
        "".join(SYM.values()).encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        SYM.update(_ASCII)

    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        _color = False
        return
    if os.name == "nt":
        os.system("")  # switches the Windows console into ANSI mode
    _color = True


def _style(code: str) -> Callable[[object], str]:
    return lambda text: f"\033[{code}m{text}\033[0m" if _color else str(text)


bold = _style("1")
dim = _style("2")
red = _style("31")
green = _style("32")
yellow = _style("33")
cyan = _style("36")


def info(msg: str) -> None:
    print(f"{dim(time.strftime('%H:%M:%S'))} {msg}", flush=True)


def success(msg: str) -> None:
    print(f"{green(SYM['ok'])} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"{yellow(SYM['warn'])} {msg}", flush=True)


def heading(msg: str) -> None:
    print(f"\n{bold(msg)}", flush=True)


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

@dataclass
class Option:
    value: Any
    label: str
    hint: str = ""
    key: str | None = None  # shortcut instead of the running number


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        raise Aborted() from None


def _question(text: str) -> None:
    print(f"\n{cyan('?')} {bold(text)}")


def select(question: str, options: Sequence[Option], default: int = 0) -> Any:
    _question(question)
    keys = [o.key or str(i + 1) for i, o in enumerate(options)]
    width = max(len(o.label) for o in options)
    for i, (key, o) in enumerate(zip(keys, options)):
        marker = cyan(SYM["pointer"]) if i == default else " "
        hint = f"  {dim(o.hint)}" if o.hint else ""
        print(f"  {marker} {key:>2}) {o.label.ljust(width)}{hint}")
    while True:
        answer = _ask(f"  Choice [{keys[default]}]: ").strip().lower()
        if not answer:
            return options[default].value
        if answer in keys:
            return options[keys.index(answer)].value
        print(red(f"  Please enter one of: {', '.join(keys)}"))


def checkbox(question: str, options: Sequence[Option], selected: Sequence[int]) -> list[Any]:
    _question(question)
    for i, o in enumerate(options):
        mark = green("x") if i in selected else " "
        hint = f"  {dim(o.hint)}" if o.hint else ""
        print(f"    {i + 1:>2}) [{mark}] {o.label}{hint}")
    current = ",".join(str(i + 1) for i in sorted(selected)) or "-"
    while True:
        answer = _ask(f"  Numbers, e.g. 1,3 (a = all) [{current}]: ").strip().lower()
        if not answer:
            chosen = sorted(selected)
        elif answer in ("a", "all", "*"):
            chosen = list(range(len(options)))
        else:
            try:
                chosen = sorted({int(t) - 1 for t in answer.replace(",", " ").split()})
            except ValueError:
                chosen = [-1]
            if any(i < 0 or i >= len(options) for i in chosen):
                print(red(f"  Use numbers from 1 to {len(options)}."))
                continue
        if not chosen:
            print(red("  Select at least one."))
            continue
        return [options[i].value for i in chosen]


def confirm(question: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = _ask(f"\n{cyan('?')} {bold(question)} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "j", "ja"):
            return True
        if answer in ("n", "no", "nein"):
            return False
        print(red("  Please answer y or n."))


def text(question: str, default: str = "", validate: Callable[[str], str | None] | None = None) -> str:
    shown = f" [{default}]" if default else ""
    while True:
        answer = _ask(f"\n{cyan('?')} {bold(question)}{shown}: ").strip() or default
        error = validate(answer) if validate else None
        if not error:
            return answer
        print(red(f"  {error}"))


def integer(question: str, default: int, minimum: int, maximum: int) -> int:
    def check(value: str) -> str | None:
        if not value.lstrip("-").isdigit() or not minimum <= int(value) <= maximum:
            return f"Enter a whole number from {minimum} to {maximum}."
        return None

    return int(text(f"{question} ({minimum}-{maximum})", str(default), check))
