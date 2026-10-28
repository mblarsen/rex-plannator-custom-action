#!/usr/bin/env python3
"""Install or remove the Pi companion symlink without changing Rex configuration."""
import argparse
import os
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().with_name("pi-extension.ts")


def agent_directory(explicit=None):
    value = explicit or os.environ.get("PI_CODING_AGENT_DIR") or str(Path.home() / ".pi/agent")
    return Path(value).expanduser().resolve()


def manage(action, directory, source=SOURCE):
    target = directory / "extensions/rex-plannotator.ts"
    if action == "install" and not source.is_file():
        raise RuntimeError(f"Companion extension is missing: {source}")
    if target.is_symlink():
        if target.resolve() != source.resolve():
            raise RuntimeError(f"Refusing to change another symlink: {target}")
        if action == "uninstall":
            target.unlink()
            return f"Removed {target}"
        return f"Already installed: {target}"
    if target.exists():
        raise RuntimeError(f"Refusing to change an existing file or directory: {target}")
    if action == "uninstall":
        return f"Not installed: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source.resolve())
    return f"Installed {target} -> {source.resolve()}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("install", "uninstall"), default="install")
    parser.add_argument("--agent-dir", help="Pi agent directory (default: PI_CODING_AGENT_DIR or ~/.pi/agent)")
    args = parser.parse_args(argv)
    try:
        print(manage(args.action, agent_directory(args.agent_dir)))
        print("Run /reload in Pi to apply the change.")
    except (OSError, RuntimeError) as error:
        print(f"Plannotator: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
