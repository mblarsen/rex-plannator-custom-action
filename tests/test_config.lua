local actions, bindings, exec_argv, split_args
local function reset()
  actions, bindings, exec_argv, split_args = {}, {}, nil, nil
  rex = {
    action = function(action) actions[action.name] = action end,
    bind = function(key, action) bindings[key] = action end,
    block = { call = function()
      return { foreground = { pid = 123, cwd = "/project" } }
    end },
    exec = function(argv)
      exec_argv = argv
      return { ok = true }
    end,
    session = { new_split = function(args)
      split_args = args
      return { block_ids = { "review" } }
    end },
    layout = { block = function(args) return args end },
  }
end
local function count(items)
  local total = 0
  for _ in pairs(items) do total = total + 1 end
  return total
end
local function includes(argv, flag, value)
  for i, item in ipairs(argv) do
    if item == flag and (value == nil or argv[i + 1] == value) then return true end
  end
  return false
end
local directory = assert(os.getenv("PWD"), "Run these tests from the repository root")
local module = dofile(directory .. "/init.lua")
local ctx = { block_id = "pi", session_id = "session" }
local passed = 0
local function test(name, fn)
  reset()
  fn()
  passed = passed + 1
  print("ok - " .. name)
end

test("default bindings and named actions", function()
  module.setup()
  assert(count(actions) == 2 and count(bindings) == 2)
  assert(bindings["ctrl+b>shift+o"] == "plannotator_pick")
  assert(bindings["ctrl+b>ctrl+o"] == "plannotator_newest")
end)

test("disable all bindings", function()
  module.setup({ keys = false })
  assert(count(actions) == 2 and count(bindings) == 0)
end)

test("custom binding and individually disabled action binding", function()
  module.setup({ keys = { pick = "cmd+o", newest = false } })
  assert(count(bindings) == 1 and bindings["cmd+o"] == "plannotator_pick")
end)

test("default split and interpreter", function()
  module.setup()
  actions.plannotator_pick.run(ctx)
  assert(exec_argv[1] == "python3")
  assert(exec_argv[2] == directory .. "/bridge.py")
  assert(exec_argv[#exec_argv] == "--check")
  assert(split_args.session_id == "session" and split_args.anchor_id == "pi")
  assert(split_args.direction == "horizontal" and split_args.side == "after")
  assert(split_args.ratio == 0.5 and split_args.focus)
  assert(not includes(split_args.layout.options.command, "--check"))
  assert(not includes(split_args.layout.options.command, "--newest"))
end)

test("directory require loads the clone entry point", function()
  local parent, name = directory:match("^(.*)/([^/]+)$")
  local previous = package.path
  package.path = parent .. "/?/init.lua;" .. package.path
  local plugin = require(name)
  package.path = previous
  plugin.setup({ keys = false })
  actions.plannotator_pick.run(ctx)
  assert(exec_argv[2] == directory .. "/bridge.py")
end)

test("custom paths and layout", function()
  module.setup({ helper = "/custom/bridge.py", python = "/custom/python3",
    tui = "/custom/tui", rex = "/custom/rex",
    agent_dir = "/custom/pi", split = {
      direction = "vertical", side = "before", ratio = 0.35, focus = false,
    } })
  actions.plannotator_newest.run(ctx)
  assert(exec_argv[1] == "/custom/python3" and exec_argv[2] == "/custom/bridge.py")
  assert(includes(exec_argv, "--tui", "/custom/tui"))
  assert(includes(exec_argv, "--rex", "/custom/rex"))
  assert(includes(exec_argv, "--agent-dir", "/custom/pi"))
  assert(includes(exec_argv, "--newest"))
  assert(split_args.direction == "vertical" and split_args.side == "before")
  assert(split_args.ratio == 0.35 and split_args.focus == false)
end)

test("invalid layouts fail before actions register", function()
  for _, split in ipairs({ { direction = "diagonal" }, { side = "right" },
      { ratio = 0 }, { ratio = 1 }, { ratio = "0.5" } }) do
    assert(not pcall(module.setup, { split = split }))
  end
  assert(count(actions) == 0)
end)

test("preflight failure does not create a pane", function()
  module.setup()
  rex.exec = function() return { ok = false, stderr = "Missing TUI" } end
  local ok, err = pcall(actions.plannotator_pick.run, ctx)
  assert(not ok and tostring(err):find("Missing TUI"))
  assert(split_args == nil)
end)

test("absent focus is refused", function()
  module.setup()
  assert(not pcall(actions.plannotator_pick.run, {}))
  assert(split_args == nil)
end)

print(passed .. " Lua tests passed")
