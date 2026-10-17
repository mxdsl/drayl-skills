"""Unit tests for drayl_check.py (no physical input needed).

Run: python -m unittest discover -s tests -v
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "drayl-check" / "scripts" / "drayl_check.py"


def platform_release():
    import platform
    return platform.release()


def child(code: str):
    return [sys.executable, "-c", code]


def load_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("drayl_check", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DraylCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / ".drayl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, name, steps, code, *extra, timeout=60):
        cmd = [sys.executable, str(SCRIPT), "run", "--name", name, "--steps", str(steps),
               "--abort-key", "none", "--build", "test", "--state-dir", str(self.state), *extra, "--"] + child(code)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        state = json.loads((self.state / "runs" / (name + ".json")).read_text(encoding="utf-8"))
        return p, state

    def test_pass(self):
        p, s = self.run_check("ok", 2, "print('DRAYL-STEP PASS one'); print('DRAYL-STEP PASS two -- 12 ms')")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(s["result"], "PASS")
        self.assertEqual(s["last_completed_step"], {"index": 2, "label": "two", "result": "PASS"})
        self.assertEqual(s["steps"][1]["note"], "12 ms")
        self.assertIn("DRAYL RESULT PASS ok 2/2", p.stdout)

    def test_fail_is_product_verdict(self):
        p, s = self.run_check("bad", 3, "print('DRAYL-STEP PASS a'); print('DRAYL-STEP FAIL b -- 1500 ms > 1000'); print('DRAYL-STEP PASS c')")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(s["result"], "FAIL")
        self.assertIn('step 2 "b" failed', s["reason"])

    def test_fail_then_crash_stays_fail(self):
        p, s = self.run_check("bad2", 3, "print('DRAYL-STEP FAIL a'); raise SystemExit(4)")
        self.assertEqual(s["result"], "FAIL")

    def test_missing_steps_is_interrupted_not_pass(self):
        p, s = self.run_check("short", 3, "print('DRAYL-STEP PASS a'); print('DRAYL-STEP PASS b')")
        self.assertEqual(p.returncode, 3)
        self.assertEqual(s["result"], "INTERRUPTED")
        self.assertEqual(s["last_completed_step"]["index"], 2)
        self.assertIn('after step 2/3 "b"', p.stdout)

    def test_crash_is_interrupted(self):
        p, s = self.run_check("crash", 2, "print('DRAYL-STEP PASS a'); raise SystemExit(7)")
        self.assertEqual(s["result"], "INTERRUPTED")
        self.assertEqual(s["exit_code"], 7)

    def test_too_many_steps_is_interrupted(self):
        p, s = self.run_check("extra", 1, "print('DRAYL-STEP PASS a'); print('DRAYL-STEP PASS b')")
        self.assertEqual(s["result"], "INTERRUPTED")

    def test_timeout_is_interrupted_and_keeps_last_step(self):
        p, s = self.run_check("slow", 3, "import time; print('DRAYL-STEP PASS a', flush=True); time.sleep(30)", "--timeout", "2")
        self.assertEqual(p.returncode, 3)
        self.assertEqual(s["result"], "INTERRUPTED")
        self.assertIn("timeout", s["reason"])
        self.assertEqual(s["last_completed_step"]["label"], "a")

    def test_non_step_lines_are_echoed(self):
        p, s = self.run_check("echo", 1, "print('hello'); print('DRAYL-STEP PASS a')")
        self.assertIn("hello", p.stdout)

    def test_stale_running_state_becomes_interrupted(self):
        runs = self.state / "runs"
        runs.mkdir(parents=True)
        stale = {"name": "stale", "result": "RUNNING", "host": socket.gethostname(), "runner_pid": 999999,
                 "steps_expected": 4, "steps": [{"index": 1, "label": "warmup", "result": "PASS"}],
                 "last_completed_step": {"index": 1, "label": "warmup", "result": "PASS"}, "updated": "x"}
        (runs / "stale.json").write_text(json.dumps(stale), encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "status", "--state-dir", str(self.state)],
                           capture_output=True, text=True, timeout=30)
        self.assertIn("INTERRUPTED", p.stdout)
        self.assertIn('after step 1/4 "warmup"', p.stdout)
        s = json.loads((runs / "stale.json").read_text(encoding="utf-8"))
        self.assertEqual(s["result"], "INTERRUPTED")
        hist = (self.state / "history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(hist), 1)

    def test_live_running_state_is_not_touched(self):
        runs = self.state / "runs"
        runs.mkdir(parents=True)
        live = {"name": "live", "result": "RUNNING", "host": socket.gethostname(), "runner_pid": os.getpid(),
                "steps_expected": 2, "steps": [], "last_completed_step": None}
        (runs / "live.json").write_text(json.dumps(live), encoding="utf-8")
        lock = load_module().NameLock(self.state, "live")
        self.assertTrue(lock.try_acquire())
        try:
            lock.write_owner()
            subprocess.run([sys.executable, str(SCRIPT), "status", "--state-dir", str(self.state)],
                           capture_output=True, text=True, timeout=30)
            s = json.loads((runs / "live.json").read_text(encoding="utf-8"))
            self.assertEqual(s["result"], "RUNNING")
            p = subprocess.run([sys.executable, str(SCRIPT), "run", "--name", "live", "--steps", "1", "--abort-key", "none",
                                "--state-dir", str(self.state), "--"] + child("print('DRAYL-STEP PASS a')"),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, load_module().EXIT_LOCK)
            self.assertNotEqual(p.returncode, 2)
            self.assertIn("already running", p.stderr)
            self.assertIn(str(os.getpid()), p.stderr)
        finally:
            lock.release()

    def test_foreign_host_running_state_is_not_touched(self):
        runs = self.state / "runs"
        runs.mkdir(parents=True)
        st = {"name": "far", "result": "RUNNING", "host": "some-other-host", "runner_pid": 1,
              "steps_expected": 2, "steps": [], "last_completed_step": None}
        (runs / "far.json").write_text(json.dumps(st), encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "status", "--json", "--state-dir", str(self.state)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(p.stdout)["result"], "RUNNING")
        self.assertFalse((self.state / "history.jsonl").exists())
        p = subprocess.run([sys.executable, str(SCRIPT), "run", "--name", "far", "--steps", "1", "--abort-key", "none",
                            "--state-dir", str(self.state), "--"] + child("print('DRAYL-STEP PASS a')"),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertIn("some-other-host", p.stderr)
        self.assertEqual(json.loads((runs / "far.json").read_text(encoding="utf-8"))["result"], "RUNNING")

    def test_status_json_stays_parseable_with_stale_run(self):
        runs = self.state / "runs"
        runs.mkdir(parents=True)
        st = {"name": "old", "result": "RUNNING", "host": socket.gethostname(), "runner_pid": 999999,
              "steps_expected": 2, "steps": [], "last_completed_step": None}
        (runs / "old.json").write_text(json.dumps(st), encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "status", "--json", "--state-dir", str(self.state)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(p.stdout)["result"], "INTERRUPTED")
        self.assertIn("INTERRUPTED", p.stderr)

    def test_fail_then_timeout_stays_fail(self):
        p, s = self.run_check("failslow", 3, "import time; print('DRAYL-STEP FAIL broken', flush=True); time.sleep(30)",
                              "--timeout", "2")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(s["result"], "FAIL")
        self.assertIn("timeout", s["reason"])

    def test_second_run_with_same_name_is_refused(self):
        first = subprocess.Popen([sys.executable, str(SCRIPT), "run", "--name", "busy", "--steps", "1", "--abort-key", "none",
                                  "--state-dir", str(self.state), "--"] + child("import time; time.sleep(4); print('DRAYL-STEP PASS a')"),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            owner = self.state / "locks" / "busy.owner.json"
            for _ in range(100):
                if owner.exists():
                    break
                import time
                time.sleep(0.05)
            p = subprocess.run([sys.executable, str(SCRIPT), "run", "--name", "busy", "--steps", "1", "--abort-key", "none",
                                "--state-dir", str(self.state), "--"] + child("print('DRAYL-STEP PASS a')"),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, load_module().EXIT_LOCK)
            self.assertIn("already running", p.stderr)
        finally:
            out, _ = first.communicate(timeout=30)
        self.assertEqual(first.returncode, 0, out)
        self.assertFalse((self.state / "locks" / "busy.owner.json").exists())
        lock = load_module().NameLock(self.state, "busy")
        self.assertTrue(lock.try_acquire())
        lock.release()

    def test_owner_suffix_name_does_not_collide(self):
        p1, s1 = self.run_check("check.owner", 1, "print('DRAYL-STEP PASS a')")
        p2, s2 = self.run_check("check", 1, "print('DRAYL-STEP PASS a')")
        self.assertEqual((s1["result"], s2["result"]), ("PASS", "PASS"))
        self.assertTrue((self.state / "runs" / "check.owner.json").exists())
        p = subprocess.run([sys.executable, str(SCRIPT), "status", "--json", "--state-dir", str(self.state)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(sorted(json.loads(x)["name"] for x in p.stdout.splitlines()), ["check", "check.owner"])

    def test_descendants_are_cleaned_up_after_leader_exits(self):
        pidfile = Path(self.tmp.name) / "grandchild.pid"
        code = ("import subprocess, sys; "
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "open(%r, 'w').write(str(g.pid)); print('DRAYL-STEP PASS spawned', flush=True)" % str(pidfile))
        p, s = self.run_check("tree", 1, code)
        self.assertEqual(s["result"], "PASS", p.stdout + p.stderr)
        mod = load_module()
        gpid = int(pidfile.read_text())
        import time
        for _ in range(50):
            if not mod.pid_alive(gpid):
                break
            time.sleep(0.1)
        self.assertFalse(mod.pid_alive(gpid), "grandchild %d still alive" % gpid)

    def test_history_appends_every_result(self):
        self.run_check("h", 1, "print('DRAYL-STEP PASS a')")
        self.run_check("h", 1, "raise SystemExit(1)")
        hist = [json.loads(x) for x in (self.state / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([h["result"] for h in hist], ["PASS", "INTERRUPTED"])

    def test_os_version_is_exact(self):
        p, s = self.run_check("osv", 1, "print('DRAYL-STEP PASS a')")
        v = s["os_version"]
        self.assertRegex(v, r"\d+\.\d+")
        if sys.platform == "darwin":
            self.assertRegex(v, r"^macOS \d+\.\d+(\.\d+)? \(\w+\)$")
        elif os.name == "nt":
            self.assertRegex(v, r"^Windows .*\d+\.\d+\.\d+(\.\d+)?$")
        elif sys.platform.startswith("linux"):
            kernel = platform_release()
            if Path("/etc/os-release").is_file():
                self.assertIn("(kernel %s)" % kernel, v)
                self.assertFalse(v.startswith("Linux "))
            else:
                self.assertEqual(v, "Linux %s" % kernel)
        self.assertIsNone(s["os_changed_from"])
        self.assertNotIn("OS changed", p.stdout)

    def test_linux_os_version_uses_distro_and_kernel(self):
        mod = load_module()
        text = 'NAME="Debian GNU/Linux"\nVERSION="12 (bookworm)"\nPRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
        self.assertEqual(mod.linux_os_version("6.1.0-18-amd64", text),
                         "Debian GNU/Linux 12 (bookworm) (kernel 6.1.0-18-amd64)")
        name_only = "NAME=Alpine\nVERSION_ID=3.20\n"
        self.assertEqual(mod.linux_os_version("6.6.0", name_only), "Alpine (kernel 6.6.0)")
        named = 'NAME="Alpine Linux"\nVERSION="3.20.0"\n'
        self.assertEqual(mod.linux_os_version("6.6.0", named), "Alpine Linux 3.20.0 (kernel 6.6.0)")
        self.assertEqual(mod.linux_os_version("6.6.0", ""), "Linux 6.6.0")

    def test_nonzero_exit_after_every_step_is_interrupted(self):
        p, s = self.run_check("fullbad", 1, "print('DRAYL-STEP PASS a'); raise SystemExit(4)")
        self.assertEqual(p.returncode, 3)
        self.assertEqual(s["result"], "INTERRUPTED")
        self.assertIn("reported every step but exited 4", s["reason"])

    def test_lock_collision_returns_dedicated_exit_code(self):
        mod = load_module()
        self.assertEqual(mod.EXIT_LOCK, 4)
        self.assertNotIn(mod.EXIT_LOCK, (0, 1, 2, 3))
        lock = mod.NameLock(self.state, "held")
        self.assertTrue(lock.try_acquire())
        try:
            lock.write_owner()
            p = subprocess.run([sys.executable, str(SCRIPT), "run", "--name", "held", "--steps", "1",
                                "--abort-key", "none", "--state-dir", str(self.state), "--"] + child(
                                    "print('DRAYL-STEP PASS a')"),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, mod.EXIT_LOCK)
            self.assertNotEqual(p.returncode, 2)
            self.assertIn("already running", p.stderr)
            self.assertFalse((self.state / "runs" / "held.json").exists())
        finally:
            lock.release()

    def test_negative_timeout_is_usage_error(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "run", "--name", "neg", "--steps", "1",
                            "--timeout", "-5", "--abort-key", "none", "--state-dir", str(self.state),
                            "--"] + child("print('DRAYL-STEP PASS a')"),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 2)
        self.assertIn("--timeout", p.stderr)
        self.assertFalse((self.state / "runs" / "neg.json").exists())

    def test_sigint_writes_interrupted_before_returning(self):
        if os.name == "nt":
            self.skipTest("console Ctrl+C delivery differs on Windows")
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT), "run", "--name", "sig", "--steps", "2", "--abort-key", "none",
             "--build", "test", "--state-dir", str(self.state), "--"] + child(
                 "import time; print('DRAYL-STEP PASS a', flush=True); time.sleep(30)"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        state_path = self.state / "runs" / "sig.json"
        seen = False
        for _ in range(100):
            if state_path.exists():
                try:
                    cur = json.loads(state_path.read_text(encoding="utf-8"))
                except ValueError:
                    cur = None
                if cur and cur.get("last_completed_step"):
                    seen = True
                    break
            time.sleep(0.05)
        if not seen:
            proc.kill()
            self.fail("runner did not record a step before the signal")
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 3, out + err)
        s = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(s["result"], "INTERRUPTED")
        self.assertEqual(s["reason"], "Ctrl+C")
        self.assertIn("DRAYL RESULT INTERRUPTED", out)

    def test_concurrent_runs_keep_history_lines_intact(self):
        procs = []
        for name in ("c1", "c2", "c3"):
            procs.append(subprocess.Popen(
                [sys.executable, str(SCRIPT), "run", "--name", name, "--steps", "1", "--abort-key", "none",
                 "--build", "test", "--state-dir", str(self.state), "--"] + child("print('DRAYL-STEP PASS a')"),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for proc in procs:
            out, err = proc.communicate(timeout=30)
            self.assertEqual(proc.returncode, 0, out + err)
        lines = (self.state / "history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        names = sorted(json.loads(line)["name"] for line in lines)
        self.assertEqual(names, ["c1", "c2", "c3"])

    def _seed_history(self, name, result, os_version, host=None):
        self.state.mkdir(parents=True, exist_ok=True)
        entry = {"name": name, "result": result, "host": host or socket.gethostname()}
        if os_version is not None:
            entry["os_version"] = os_version
        with open(self.state / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def test_os_change_since_last_comparable_run_is_reported(self):
        self._seed_history("upd", "PASS", "Test OS 1.0 (A1)")
        p, s = self.run_check("upd", 1, "print('DRAYL-STEP PASS a')")
        self.assertEqual(s["os_changed_from"], "Test OS 1.0 (A1)")
        self.assertIn("DRAYL note: OS changed since the last PASS/FAIL run of upd", p.stdout)
        st = subprocess.run([sys.executable, str(SCRIPT), "status", "--name", "upd", "--state-dir", str(self.state)],
                            capture_output=True, text=True, timeout=30)
        self.assertIn("OS changed: Test OS 1.0 (A1) ->", st.stdout)
        # The run just recorded the current OS; the next one compares against it.
        p2, s2 = self.run_check("upd", 1, "print('DRAYL-STEP PASS a')")
        self.assertIsNone(s2["os_changed_from"])
        self.assertNotIn("OS changed", p2.stdout)

    def test_os_change_ignores_interrupted_other_host_and_old_records(self):
        self._seed_history("ign", "INTERRUPTED", "Test OS 1.0 (A1)")
        self._seed_history("ign", "PASS", "Test OS 1.0 (A1)", host="some-other-host")
        self._seed_history("ign", "FAIL", None)
        p, s = self.run_check("ign", 1, "print('DRAYL-STEP PASS a')")
        self.assertIsNone(s["os_changed_from"])
        self.assertNotIn("OS changed", p.stdout)

    def test_truncated_history_line_does_not_block_runs(self):
        self._seed_history("cut", "PASS", "Test OS 1.0 (A1)")
        with open(self.state / "history.jsonl", "ab") as f:
            f.write('{"name": "cut", "os_version": "Ä'.encode("utf-8")[:-1] + b"\n[1]\n")
        p, s = self.run_check("cut", 1, "print('DRAYL-STEP PASS a')")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(s["os_changed_from"], "Test OS 1.0 (A1)")

    def test_child_gets_run_env(self):
        p, s = self.run_check("env", 1, "import os; print('DRAYL-STEP PASS ' + os.environ['DRAYL_RUN_NAME'])")
        self.assertEqual(s["steps"][0]["label"], "env")


if __name__ == "__main__":
    unittest.main()
