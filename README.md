# Plannotator custom actions for Rex

Annotate a Pi reply in a separate Rex pane, then send the feedback to Pi.
The reply picker and annotation UI come from [Plannotator TUI](https://github.com/plannotator/plannotator-tui).
This project adds Rex actions, keyboard shortcuts, and feedback delivery.

Rex loads the Lua module from `init.lua`. This is a custom-action module, not a Rex plugin package.
The Python helper handles the pseudo-terminal, resize events, clipboard exports, and feedback delivery.
It uses the standard library. There are no Python package dependencies.

## Requirements

| Requirement | Why it is needed |
| --- | --- |
| Rex with Lua actions, `rex.exec`, `session.new_split`, terminal `process`, and `program_status` | Opens the review pane and identifies the focused process. |
| Python 3.10 or newer | Runs the terminal bridge. Python resolves through PATH, regardless of its installation method. |
| Standalone `plannotator-tui` | Provides the reply picker and annotation UI. No binary is bundled here. |
| Pi with this repository's `pi-extension.ts` loaded | Reports the exact Pi conversation UUID to Rex through OSC 7501. |
| A file-backed Pi session | Supplies the JSONL transcript. Session names are not used for targeting. |
| macOS or Linux | The helper uses POSIX pseudo-terminals. Windows is not supported. |

Run Rex, Pi, and the helper on the same host and as the same user.
Intercom and Herdr are not required.
Remote and cross-host workflows are not supported.

Development used Rex CLI `0.0.1793047680-g2db882`, Pi 1.4.0, and Plannotator TUI 0.9.4 and 0.9.7 on macOS.
Use a TUI release with `last --session`, the reply picker, OSC 52 exports, and the default `S` send-and-close key.
These capability requirements are more precise than an untested minimum Rex version.

### Install the standalone TUI

On macOS or Linux with Homebrew:

```sh
brew trust plannotator/tap
brew install plannotator/tap/plannotator-tui
```

`brew trust` is the Homebrew 6 tap approval step. Older Homebrew versions may not need it.
Alternatively, install with `cargo install plannotator-tui` or use an
[official release](https://github.com/plannotator/plannotator-tui/releases).
For release downloads, verify the binary against the release's `SHA256SUMS` file.

Make these commands available to the Rex server:

```sh
python3 --version
plannotator-tui --version
```

The `plannotator` browser CLI is not needed.

## Install the custom actions

Clone into Rex's configuration directory:

```sh
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/rex"
mkdir -p "$config_dir"
git clone https://github.com/mblarsen/rex-plannator-custom-action.git \
  "$config_dir/rex-plannator-custom-action"
cd "$config_dir/rex-plannator-custom-action"
```

Rex loads modules beside the `init.lua` path it opens.
If your `init.lua` is a symlink, clone beside the symlink, not its target.
For a custom Rex config location, use that directory instead.
The module finds `bridge.py` beside its own source. Do not copy runtime files out of the clone.

Install the companion symlink:

```sh
python3 install.py
```

The installer links Pi's `extensions/rex-plannotator.ts` to `pi-extension.ts` in this clone.
It uses `PI_CODING_AGENT_DIR`, or `~/.pi/agent` when the variable is unset.
Use `python3 install.py --agent-dir /absolute/path/to/pi-agent` for a custom Pi agent directory.
Use the same `agent_dir` in the Lua options when Rex does not inherit that environment variable.

Repeated installation leaves the existing link unchanged.
The installer refuses to overwrite a regular file, directory, or link to another location.
It does not edit your Rex configuration or Pi settings.

Run `/reload` in Pi, or restart Pi. The extension only emits status inside an interactive Rex terminal.
It adds no commands, tools, timers, sockets, or external dependencies.
Pi's native status reports do not include its conversation UUID; this extension supplies that missing link.
It uses a separate status record and does not replace Pi's normal busy, dialog, or completion status.

Add this line to your existing Rex `init.lua`. Do not replace unrelated configuration:

```lua
require("rex-plannator-custom-action").setup()
```

Check and reload:

```sh
rex config check
rex config reload
```

No Rex restart is needed. Open a new review after changing the helper or its options.

## Default keys

| Key sequence | Action |
| --- | --- |
| Ctrl+B, then Shift+O | Pick a Pi assistant reply. |
| Ctrl+B, then Ctrl+O | Open the newest Pi assistant reply. |

Inside the review:

- Press `p` to choose another reply.
- Select text, then press `c` to comment, `a` for looks good, or `d` for delete.
- Press `Shift+S` to copy feedback, close the review, and submit the feedback to Pi.
- Press `E`, then `q` to close and paste the feedback without submitting it.
- Quit without an export to leave Pi's input unchanged.

The original Pi pane receives the feedback, even if focus changes during the review.
The helper checks the process and session again before delivery.

A prefix binding consumes Ctrl+B in Rex. If you want a pass-through sequence, add it explicitly:

```lua
rex.bind("ctrl+b>ctrl+b", "pane.send_key", { key = "ctrl+b" })
```

The module does not install a pass-through binding or replace your other prefix commands.

## Configure

### Change or disable the default bindings

```lua
require("rex-plannator-custom-action").setup({
  keys = {
    pick = "ctrl+a>shift+o",
    newest = "ctrl+a>ctrl+o",
  },
})
```

Set either key to `false` to disable that binding. Both actions still appear in the command palette.

To manage all bindings yourself:

```lua
require("rex-plannator-custom-action").setup({ keys = false })

rex.bind("ctrl+b>shift+o", "plannotator_pick")
rex.bind("ctrl+b>ctrl+o", "plannotator_newest")
```

Calling `setup` without `keys = false` installs the two default shortcuts.
Do not call `setup` more than once. Remove old custom bindings when changing sequences, then reload the config.

### Change the split layout

The default is a focused, equal-width split to the right of Pi.
This example places the review below Pi:

```lua
require("rex-plannator-custom-action").setup({
  split = {
    direction = "vertical", -- horizontal: left/right; vertical: above/below
    side = "after",         -- before: left/top; after: right/bottom
    ratio = 0.4,            -- fraction allocated to the left/top side
    focus = true,
  },
})
```

Rex's `ratio` describes the first side, not always the review pane.
With `side = "after"` and `ratio = 0.4`, Pi gets 40 percent and the review gets 60 percent.
The ratio must be greater than zero and less than one.

### Change helper and executable locations

Each executable defaults to a command name on PATH. The helper defaults to `bridge.py` beside the module.
Combine any of these options in one `setup` call:

```lua
local home = os.getenv("HOME")

require("rex-plannator-custom-action").setup({
  python = "python3",
  tui = "plannotator-tui",
  rex = "rex",
  agent_dir = home .. "/.pi/agent",
})
```

To override helper discovery, set `helper = "/absolute/path/to/bridge.py"` in the same options table.
`helper` and `agent_dir` should be absolute paths. Executable options accept a command name or an absolute path, without shell flags.
Arguments are passed directly, so paths with spaces need no extra quotes inside the Lua strings.

Without an explicit `agent_dir`, the helper uses `PI_CODING_AGENT_DIR` or `~/.pi/agent`.
That variable must be available to the Rex server, not just a child shell.
The helper also checks `~/.local/bin` for executables.
For Rex itself, it checks `REX_BIN_DIR` and Rex's standard per-user macOS installation location.
Explicit executable options take precedence and fail if the executable cannot be found.

## Targeting and limits

1. Read the focused terminal's foreground PID, process name, and directory from Rex.
2. Read the companion's `plannotator/<uuid-hex>` status record owned by that process.
3. Locate the transcript with that UUID under the configured Pi agent directory.
4. Verify its header UUID and working directory.
5. Open the TUI with the exact transcript path.

`REX_BLOCK` is a stable pane ID, and `REX_SESSION` identifies the Rex workspace.
Neither is a Pi conversation ID. Rex's process API deliberately omits command arguments and does not expose process environment variables.
Pi's native status record contains human-readable state but no conversation UUID.
The companion publishes the UUID in a dedicated machine-readable record ID, rather than putting metadata into a display message.
The UUID has its hyphens removed to fit the protocol's 32-character ID segment limit.

The bridge refuses missing or ambiguous matches. It never selects the newest transcript or matches a session name.
The companion clears its record on shutdown, session replacement, and reload, and publishes the current UUID in the new runtime.
It republishes at agent start and settlement to recover from terminal status resets.

The helper supports Pi's default UUID-suffixed transcript filenames below `agent_dir/sessions`.
Custom transcript paths outside that location are not supported. In-memory sessions cannot be annotated.
The transcript must exist on disk; for a newly created session, wait until Pi has saved a reply.

Feedback delivery uses Rex's terminal input, not a Pi API. The helper uses bracketed paste to preserve newlines.
It refuses exported text with raw control characters that could break out of bracketed paste.
If Pi changed sessions or disappeared, the helper saves the feedback to a private temporary Markdown file.
The review terminal reports that path.

`Shift+S` submission follows the TUI's default key. Custom TUI send-and-close bindings and mouse-triggered submission are not supported.
The bridge identifies submission when a standalone `S` is the final input before the TUI exits successfully.
It does not control the TUI's displayed clipboard labels.

Each distinct clipboard export is kept. Exporting an edited review again stages both versions.
For one final version, export only when the review is ready to close.
The TUI retains its normal clipboard and feedback archive behavior.

## Upgrade

Update the clone, then reload Rex:

```sh
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/rex"
git -C "$config_dir/rex-plannator-custom-action" pull --ff-only
rex config check
rex config reload
```

Run `/reload` in Pi to load companion changes. Open a new review to use the updated helper.
The symlink follows updates to the clone. You do not need to run the installer again.

### Migrate from copied files

Clone into the config directory as described above.
If `extensions/rex-plannotator.ts` is a copied file, move it to a backup before running `python3 install.py`.
The installer deliberately refuses to replace it.
Replace the old `require("plannotator").setup(...)` line with `require("rex-plannator-custom-action").setup(...)`.
Keep your options, but remove any helper override that still points to an old copy.
Do not keep both setup calls. Reload Rex and Pi, then archive the unused copied files.

## Uninstall

From the clone, remove the companion symlink:

```sh
python3 install.py uninstall
```

Use the same `--agent-dir` option if you installed into a custom Pi agent directory.
The command removes only a symlink that points to this clone's companion.
It leaves unrelated extensions, Pi settings, and the source files unchanged.

Remove the module's setup call and any explicit annotation bindings from your Rex `init.lua`.
Run `rex config check`, `rex config reload`, and `/reload` in Pi.
After closing any open reviews, you can remove the clone if you have no local changes to keep.
Uninstall before moving the clone, then install again from its new location.

## Tests

From the repository root:

```sh
python3 -m unittest discover -s tests -v
lua tests/test_config.lua
node --experimental-strip-types --test tests/test_extension.mjs
```

The Python tests cover export parsing, UUID targeting, stale process records, ambiguous transcripts, executable overrides, and safe delivery.
Installer tests check symlink updates, repeated installation, custom paths, and refusal to change unrelated files or links.
The Lua tests cover default and custom bindings, disabled bindings, executable options, split layout, and preflight failures.
The companion tests cover protocol IDs, lifecycle cleanup, session replacement, and non-interactive guards.
Lua 5.1 matches Rex's scripting runtime. The tests also run on newer Lua versions.
Companion tests require Node.js 22.6 or newer for TypeScript stripping; Pi loads the extension itself without a build step.

For an installed-version check, add the setup call to your config and run `rex config check`.
To test a draft without changing the live config, run `rex config check /absolute/path/to/draft.lua`.

## License

MIT. Plannotator TUI, Pi, and Rex are separate dependencies with their own licenses.
