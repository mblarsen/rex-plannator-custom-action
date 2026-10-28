import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("bridge", Path(__file__).resolve().parents[1] / "bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class ExportTests(unittest.TestCase):
    def export(self, text):
        return b"\x1b]52;c;" + base64.b64encode(text.encode()) + b"\x07"

    def test_fragmented_utf8_and_terminal_noise(self):
        exports = bridge.Exports()
        data = b"screen noise" + self.export("Comment: gr\u00f8n\nnext") + b"more screen"
        for byte in data:
            exports.feed(bytes([byte]))
        self.assertEqual(exports.messages, ["Comment: gr\u00f8n\nnext"])

    def test_ignores_queries_invalid_payloads_and_control_injection(self):
        exports = bridge.Exports()
        exports.feed(b"\x1b]52;c;?\x07\x1b]52;c;invalid!\x07")
        exports.feed(self.export("bad\x1b[201~\rsubmit"))
        exports.feed(self.export("valid\ntext\tindent"))
        self.assertEqual(exports.messages, ["valid\ntext\tindent"])

    def test_multiple_exports_and_duplicates(self):
        exports = bridge.Exports()
        exports.feed(self.export("first") + self.export("first") + self.export("second"))
        self.assertEqual(exports.messages, ["first", "second"])

    def test_pending_buffer_bounded(self):
        exports = bridge.Exports()
        exports.feed(b"x" * 100000)
        self.assertLess(len(exports.pending), 20)
        exports.limit = 100
        with self.assertRaisesRegex(RuntimeError, "too large"):
            exports.feed(bridge.Exports.start + b"a" * 101)


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session_id = "01a180a8-9639-75ed-a165-86bbaa0cd84c"
        self.path = Path(self.tmp.name) / "sessions/project" / ("date_" + self.session_id + ".jsonl")
        self.path.parent.mkdir(parents=True)
        self.header = {"type": "session", "id": self.session_id, "cwd": "/project"}
        self.path.write_text(json.dumps(self.header) + "\n")
        self.args = SimpleNamespace(session="rex-session", block="target", pid=123,
                                    rex=None, agent_dir=None)
        self.records = [{"owner": {"pid": 123, "name": "node"}, "app": "pi", "state": "idle",
                         "id": "plannotator/" + self.session_id.replace("-", "")}]
        self.env = patch.dict(bridge.os.environ, {"PI_CODING_AGENT_DIR": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        patch.object(bridge, "block_call", side_effect=self.block_call).start()
        self.cmd = patch.object(bridge, "command", return_value="").start()
        patch.object(bridge, "executable", side_effect=lambda name, override=None: override or name).start()
        self.addCleanup(patch.stopall)

    def block_call(self, args, method):
        if method == "process":
            return {"foreground": {"pid": 123, "name": "node", "cwd": "/project"}}
        return {"records": self.records}

    def test_exact_transcript_not_newest_in_directory(self):
        (self.path.parent / "newer_different-session.jsonl").write_text("{}\n")
        self.assertEqual(bridge.resolve(self.args), (self.path, "/project"))

    def test_name_and_root_status_are_not_identity(self):
        self.records.append({"owner": {"pid": 123, "name": "node"}, "app": "pi",
                             "state": "blocked", "msg": "A dialog instead of a session name"})
        self.assertEqual(bridge.resolve(self.args)[0], self.path)

    def test_process_changed(self):
        self.args.pid = 124
        with self.assertRaisesRegex(RuntimeError, "process changed"):
            bridge.resolve(self.args)

    def test_multiple_conversation_ids_refused(self):
        self.records.append({**self.records[0], "id": "plannotator/" + "a" * 32})
        with self.assertRaisesRegex(RuntimeError, "No unique Pi conversation ID"):
            bridge.resolve(self.args)

    def test_other_process_status_refused(self):
        self.records[0]["owner"]["pid"] = 456
        with self.assertRaisesRegex(RuntimeError, "No unique Pi"):
            bridge.resolve(self.args)

    def test_reused_pid_with_other_process_name_refused(self):
        self.records[0]["owner"]["name"] = "other"
        with self.assertRaisesRegex(RuntimeError, "No unique Pi"):
            bridge.resolve(self.args)

    def test_null_status_owner_refused(self):
        self.records[0]["owner"] = None
        with self.assertRaisesRegex(RuntimeError, "No unique Pi"):
            bridge.resolve(self.args)

    def test_missing_companion_refused(self):
        self.records[0].pop("id")
        with self.assertRaisesRegex(RuntimeError, "install pi-extension.ts"):
            bridge.resolve(self.args)

    def test_invalid_id_refused(self):
        for bad in ("plannotator/../../other", "plannotator/" + "g" * 32,
                    "plannotator/" + "a" * 31, "other/" + "a" * 32):
            self.records[0]["id"] = bad
            with self.assertRaisesRegex(RuntimeError, "No unique Pi"):
                bridge.resolve(self.args)

    def test_wrong_app_refused(self):
        self.records[0]["app"] = "other"
        with self.assertRaisesRegex(RuntimeError, "No unique Pi"):
            bridge.resolve(self.args)

    def test_duplicate_transcript_refused(self):
        other = self.path.parent / "copy"
        other.mkdir()
        (other / self.path.name).write_text(self.path.read_text())
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            bridge.resolve(self.args)

    def test_header_identity_and_directory_verified(self):
        for key, value in (("id", "different"), ("cwd", "/other"), ("type", "message")):
            self.path.write_text(json.dumps({**self.header, key: value}) + "\n")
            with self.assertRaisesRegex(RuntimeError, "header does not match"):
                bridge.resolve(self.args)

    def test_custom_agent_dir(self):
        self.args.agent_dir = self.tmp.name
        with patch.dict(bridge.os.environ, {"PI_CODING_AGENT_DIR": "/not-used"}):
            self.assertEqual(bridge.resolve(self.args)[0], self.path)

    def test_custom_rex_executable(self):
        self.args.rex = "/custom/rex"
        bridge.deliver(self.args, self.path, ["feedback"])
        self.assertEqual(self.cmd.call_args.args[0][0], "/custom/rex")

    def test_missing_transcript_refused(self):
        self.path.unlink()
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            bridge.resolve(self.args)

    def test_delivery_bracketed_without_enter(self):
        bridge.deliver(self.args, self.path, ["first\nsecond"])
        self.assertEqual(self.cmd.call_args.args[0], ["rex", "send", "-s", "rex-session", "-b", "target"])
        self.assertEqual(self.cmd.call_args.kwargs["input"], "\x1b[200~first\nsecond\x1b[201~")

    def test_shift_s_submits_after_bracketed_paste(self):
        bridge.deliver(self.args, self.path, ["first\nsecond"], submit=True)
        self.assertEqual(self.cmd.call_args.kwargs["input"], "\x1b[200~first\nsecond\x1b[201~\r")

    def test_session_switch_refuses_delivery(self):
        with self.assertRaisesRegex(RuntimeError, "switched sessions"):
            bridge.deliver(self.args, Path("different.jsonl"), ["feedback"])


if __name__ == "__main__":
    unittest.main()
