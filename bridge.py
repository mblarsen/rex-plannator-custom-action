#!/usr/bin/env python3
"""Run the stock annotation picker and stage explicit clipboard exports in Pi."""
import argparse
import base64
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import tty

def executable(name, override=None):
    if override is not None:
        candidate = shutil.which(os.path.expanduser(override))
        if candidate:
            return candidate
        raise RuntimeError(f"Executable not found: {override}")
    candidates = [shutil.which(name), str(Path.home() / ".local/bin" / name)]
    if name == "rex":
        if os.environ.get("REX_BIN_DIR"):
            candidates.insert(0, str(Path(os.environ["REX_BIN_DIR"]) / name))
        # Rex's server-side actions do not inherit a terminal's REX_BIN_DIR.
        if sys.platform == "darwin":
            candidates.append(str(Path.home() / "Library/Application Support/com.superlogical.rex"
                                  / "RexServer/Versions/Current/Rex Server.app/Contents/MacOS/rex"))
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError(f"Executable not found: {name}")


def command(argv, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=10, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {argv[0]}")
    return result.stdout


def block_call(args, method):
    return json.loads(command([executable("rex", args.rex), "block", "call", "-s", args.session,
                               "-b", args.block, method]))


def resolve(args):
    process = block_call(args, "process").get("foreground") or {}
    if process.get("pid") != args.pid:
        raise RuntimeError("The target process changed; focus Pi and try again")
    records = block_call(args, "program_status").get("records", [])
    ids = set()
    for record in records:
        owner = record.get("owner") or {}
        if owner.get("pid") != args.pid or owner.get("name") != process.get("name"):
            continue
        if record.get("effective_app", record.get("app")) != "pi":
            continue
        match = re.fullmatch(r"plannotator/([0-9a-f]{32})", record.get("id", ""))
        if match:
            ids.add(match[1])
    if len(ids) != 1:
        raise RuntimeError("No unique Pi conversation ID reported by Rex; "
                           "install pi-extension.ts in Pi and reload its extensions")
    hex_id = ids.pop()
    session_id = (f"{hex_id[:8]}-{hex_id[8:12]}-{hex_id[12:16]}-"
                  f"{hex_id[16:20]}-{hex_id[20:]}")
    cwd = process.get("cwd")
    if not cwd:
        raise RuntimeError("Rex did not report the Pi process working directory")
    agent_dir = Path(args.agent_dir or os.environ.get("PI_CODING_AGENT_DIR",
                                                    str(Path.home() / ".pi/agent"))).expanduser()
    files = list((agent_dir / "sessions").glob(f"**/*_{session_id}.jsonl"))
    if len(files) != 1:
        raise RuntimeError(f"Expected one transcript for Pi conversation {session_id}, "
                           f"found {len(files)}")
    path = files[0]
    with path.open(encoding="utf-8") as file:
        header = json.loads(file.readline())
    if (not isinstance(header, dict) or header.get("type") != "session" or header.get("id") != session_id
            or header.get("cwd") != cwd):
        raise RuntimeError("Pi transcript header does not match the reported conversation and directory")
    return path, cwd


class Exports:
    """Incrementally recognize only the TUI's explicit OSC 52 clipboard writes."""
    start = b"\x1b]52;c;"
    limit = 4 * 1024 * 1024

    def __init__(self):
        self.pending = b""
        self.messages = []

    def feed(self, data):
        self.pending += data
        while True:
            start = self.pending.find(self.start)
            if start < 0:
                self.pending = self.pending[-(len(self.start) - 1):]
                return
            self.pending = self.pending[start:]
            end = self.pending.find(b"\x07", len(self.start))
            if end < 0:
                if len(self.pending) > self.limit:
                    raise RuntimeError("Clipboard export is too large")
                return
            encoded = self.pending[len(self.start):end]
            self.pending = self.pending[end + 1:]
            try:
                message = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (ValueError, UnicodeError):
                continue
            # Raw control bytes could break out of bracketed paste and submit input.
            if any(ord(c) < 32 and c not in "\n\t" for c in message):
                continue
            if message.strip() and message not in self.messages:
                self.messages.append(message)


def write_all(fd, data):
    while data:
        count = os.write(fd, data)
        data = data[count:]


def run_tui(argv, exports):
    size = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8)
    original = termios.tcgetattr(0)
    pid, master = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, size)
        # Do not accidentally inherit a Herdr delivery target from Rex's server.
        env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")}
        try:
            os.execve(argv[0], argv, env)
        except OSError as error:
            print(error, file=sys.stderr)
            os._exit(127)

    def resize(*_):
        size = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(master, termios.TIOCSWINSZ, size)

    old_handler = signal.signal(signal.SIGWINCH, resize)
    last_input = b""
    try:
        tty.setraw(0)
        while True:
            readable, _, _ = select.select([0, master], [], [])
            if master in readable:
                try:
                    data = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
                if not data:
                    break
                exports.feed(data)
                write_all(1, data)
            if 0 in readable:
                data = os.read(0, 65536)
                if not data:
                    break
                last_input = data
                write_all(master, data)
    finally:
        termios.tcsetattr(0, termios.TCSADRAIN, original)
        signal.signal(signal.SIGWINCH, old_handler)
        os.close(master)
        _, status = os.waitpid(pid, 0)
    # Only a standalone Shift+S that closes the UI requests submission.
    # An S typed in a comment is followed by other input before a clean exit.
    return os.waitstatus_to_exitcode(status), last_input == b"S"


def deliver(args, transcript, messages, submit=False):
    current, _ = resolve(args)
    if current != transcript:
        raise RuntimeError("Pi switched sessions; feedback was not pasted")
    text = "\n\n".join(messages)
    command([executable("rex", args.rex), "send", "-s", args.session, "-b", args.block],
            input="\x1b[200~" + text + "\x1b[201~" + ("\r" if submit else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--block", required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--tui", default=None, help="plannotator-tui executable or command name")
    parser.add_argument("--rex", default=None, help="Rex executable or command name")
    parser.add_argument("--agent-dir", default=None, help="Pi agent directory containing sessions/")
    parser.add_argument("--newest", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    exports = Exports()
    try:
        binary = executable("plannotator-tui", args.tui)
        transcript, cwd = resolve(args)
        if args.check:
            print(json.dumps({"transcript": str(transcript), "cwd": cwd}))
            return 0
        os.chdir(cwd)
        argv = [binary, "last", "--host", "pi", "--session", str(transcript)]
        if args.newest:
            argv.append("--newest")
        code, submit = run_tui(argv, exports)
        if code:
            raise RuntimeError(f"Annotation UI exited with status {code}")
        if exports.messages:
            deliver(args, transcript, exports.messages, submit=submit)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        if exports.messages:
            # Keep an independent recovery copy if the target vanished or changed.
            import tempfile
            fd, path = tempfile.mkstemp(prefix="rex-plannotator-", suffix=".md")
            with os.fdopen(fd, "w") as file:
                file.write("\n\n".join(exports.messages))
            print(f"Feedback saved to {path}", file=sys.stderr)
        print(f"Plannotator: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
