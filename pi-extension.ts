import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const clear = "\x1b]7501;state=clear:id=plannotator\x1b\\";

export default function (pi: ExtensionAPI) {
  let active = false;

  function publish(_event: unknown, ctx: ExtensionContext) {
    if (ctx.mode !== "tui" || !process.stdout.isTTY || !process.env.REX_BLOCK) return;
    const id = ctx.sessionManager.getSessionId();
    if (!ctx.sessionManager.getSessionFile() ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
      if (active) process.stdout.write(clear);
      active = false;
      return;
    }
    // Each OSC 7501 ID segment is limited to 32 characters; UUID hex fits.
    const hex = id.replaceAll("-", "").toLowerCase();
    process.stdout.write(clear + `\x1b]7501;state=idle:app=pi:id=plannotator/${hex}\x1b\\`);
    active = true;
  }

  pi.on("session_start", publish);
  pi.on("agent_start", publish);
  pi.on("agent_settled", publish);
  pi.on("session_shutdown", () => {
    if (active) process.stdout.write(clear);
    active = false;
  });
}
