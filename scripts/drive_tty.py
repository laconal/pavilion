"""Drive pavilion's interactive prompts in a pseudo-terminal, to check them by hand.

CliRunner tests never see the prompts (no TTY means defaults are used), so this is
how to exercise the arrow-key menus and text inputs for real.

Usage, from the directory pavilion should run in (NOT the repo root, it writes files):

    python /path/to/scripts/drive_tty.py "add auth" ENTER ENTER UP UP ENTER BS*4 4096 ENTER

Each step is a key name (ENTER, UP, DOWN, ESC, BS for backspace, BS*4 to repeat) or
literal text to type. Prints the screen output with redraws de-duplicated. The app is
killed after --timeout seconds, so steps that don't line up with the prompts can't hang.
"""

import argparse
import os
import pty
import re
import select
import signal
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEYS = {"ENTER": b"\r", "UP": b"\x1b[A", "DOWN": b"\x1b[B", "ESC": b"\x1b", "BS": b"\x7f"}


def to_bytes(step: str) -> bytes:
    name, _, count = step.partition("*")
    if name in KEYS:
        return KEYS[name] * int(count or 1)
    return step.encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", help='pavilion arguments, e.g. "add auth"')
    parser.add_argument("steps", nargs="*", help="keys to send, one step per prompt answer")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between steps")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    pid, fd = pty.fork()
    if pid == 0:
        command = ["uv", "run", "-q", "--project", str(REPO), "pavilion", *args.command.split()]
        os.execvp("uv", command)

    output = b""
    deadline = time.time() + args.timeout

    def read(seconds: float) -> None:
        nonlocal output
        end = min(time.time() + seconds, deadline)
        while time.time() < end:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    output += os.read(fd, 4096)
                except OSError:  # child exited
                    return

    read(4)  # uv startup
    for step in args.steps:
        os.write(fd, to_bytes(step))
        read(args.delay)
    read(3)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    os.waitpid(pid, 0)

    text = re.sub(rb"\x1b\[[0-9;?]*[a-zA-Z]", b"", output).decode(errors="replace")
    seen: list[str] = []
    for line in text.replace("\r", "\n").splitlines():
        line = line.rstrip()
        # The CPR warning only appears because this isn't a real terminal.
        if line.strip() and "CPR" not in line and line not in seen:
            seen.append(line)
    print("\n".join(seen))


if __name__ == "__main__":
    main()
