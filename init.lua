local M = {}
local home = os.getenv("HOME")
local source = debug.getinfo(1, "S").source:gsub("^@", "")
local directory = source:match("^(.*)/[^/]+$") or "."

function M.setup(opts)
  opts = opts or {}
  local split = opts.split or {}
  local direction = split.direction or "horizontal"
  local side = split.side or "after"
  local ratio = split.ratio or 0.5
  assert(direction == "horizontal" or direction == "vertical", "Invalid split.direction")
  assert(side == "before" or side == "after", "Invalid split.side")
  assert(type(ratio) == "number" and ratio > 0 and ratio < 1, "split.ratio must be between 0 and 1")
  local helper = opts.helper or (directory .. "/bridge.py")
  local python = opts.python or "python3"
  local function open(ctx, newest)
    if not ctx.block_id then error("Focus a Pi terminal first", 0) end
    local process, err = rex.block.call("com.superlogical.terminal", "process", {
      block_id = ctx.block_id,
    })
    if not process then error(err, 0) end
    local foreground = process.foreground
    if not foreground or not foreground.pid then error("No foreground process", 0) end
    local argv = { python, helper,
      "--session", ctx.session_id, "--block", ctx.block_id,
      "--pid", tostring(foreground.pid) }
    for _, option in ipairs({ "tui", "rex", "agent_dir" }) do
      if opts[option] then
        argv[#argv + 1] = "--" .. option:gsub("_", "-")
        argv[#argv + 1] = opts[option]
      end
    end
    if newest then argv[#argv + 1] = "--newest" end
    -- Resolve before splitting, so errors do not leave an empty pane.
    local check = {}
    for i, value in ipairs(argv) do check[i] = value end
    check[#check + 1] = "--check"
    local result, check_err = rex.exec(check, { timeout = 10 })
    if not result then error(check_err, 0) end
    if not result.ok then error(result.stderr, 0) end
    local pane, pane_err = rex.session.new_split{
      session_id = ctx.session_id,
      anchor_id = ctx.block_id,
      direction = direction,
      side = side,
      ratio = ratio,
      focus = split.focus ~= false,
      layout = rex.layout.block{
        flavor = "com.superlogical.terminal.shell",
        options = { shell = "none", command = argv, cwd = foreground.cwd or home },
      },
    }
    if not pane then error(pane_err, 0) end
    return pane
  end
  rex.action{
    name = "plannotator_pick", title = "Annotate: pick a Pi reply",
    category = "Plannotator", run = function(ctx) return open(ctx, false) end,
  }
  rex.action{
    name = "plannotator_newest", title = "Annotate: newest Pi reply",
    category = "Plannotator", run = function(ctx) return open(ctx, true) end,
  }
  if opts.keys ~= false then
    local keys = opts.keys or {}
    if keys.pick ~= false then
      rex.bind(keys.pick or "ctrl+b>shift+o", "plannotator_pick")
    end
    if keys.newest ~= false then
      rex.bind(keys.newest or "ctrl+b>ctrl+o", "plannotator_newest")
    end
  end
end

return M
