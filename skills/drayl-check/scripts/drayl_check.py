#!/usr/bin/env python3
"""drayl_check - run a live check and give it one honest result.

Results:
  PASS         every declared step reported PASS and the check exited 0
  FAIL         at least one step reported FAIL (the product is wrong)
  INTERRUPTED  the run did not finish (abort key, physical input during a
               hands-off run, Ctrl+C, timeout, crash, missing steps). The
               measurement is invalid: never a pass, never a regression,
               never a baseline.

The check is any command. It reports each finished step on stdout:

  DRAYL-STEP <PASS|FAIL> <label> [-- note]

After every step the runner rewrites the state file, so an interrupted run
always names its last completed step. Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

PASS, FAIL, INTERRUPTED = "PASS", "FAIL", "INTERRUPTED"
EXIT = {PASS: 0, FAIL: 1, INTERRUPTED: 3}
STEP_RE = re.compile(r"^DRAYL-STEP\s+(PASS|FAIL)\s+(.+?)(?:\s+--\s+(.*))?\s*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def append_history(state_dir: Path, data: dict) -> None:
    hist = state_dir / "history.jsonl"
    with open(hist, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def git_build() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        rev = out.stdout.strip()
        if out.returncode != 0 or not rev:
            return "unknown"
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10)
        return rev + ("-dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _sw_vers(flag: str) -> str:
    try:
        out = subprocess.run(["sw_vers", flag], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def os_version() -> str:
    """Exact OS version with build number. An OS update can change a live
    check's result without any change to the product, so runs on different
    OS builds are not compared as before/after."""
    system = platform.system()
    if system == "Darwin":
        # platform.mac_ver() reports 10.16 for Pythons built against old SDKs.
        ver = _sw_vers("-productVersion") or platform.mac_ver()[0] or platform.release()
        build = _sw_vers("-buildVersion")
        return "macOS %s (%s)" % (ver, build) if build else "macOS %s" % ver
    if system == "Windows":
        version = platform.version()  # 10.0.26200
        reg = {}
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
                for value in ("UBR", "DisplayVersion", "InstallationType"):
                    try:
                        reg[value] = winreg.QueryValueEx(k, value)[0]
                    except OSError:
                        pass
        except OSError:
            pass
        parts = version.split(".")
        build = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
        if str(reg.get("InstallationType", "")).startswith("Server"):  # Server, Server Core
            product = "Windows Server"
        elif parts[:1] == ["10"] and build >= 22000:
            # Windows 11 still reports major version 10; the build tells them apart.
            product = "Windows 11"
        else:
            product = "Windows %s" % platform.release()
        full = version + (".%d" % reg["UBR"] if isinstance(reg.get("UBR"), int) else "")
        display = reg.get("DisplayVersion")
        display = display if isinstance(display, str) else ""
        return " ".join(p for p in (product, display, full) if p)
    return "%s %s" % (system, platform.release())


def last_comparable_run(state_dir: Path, name: str, host: str):
    """The latest PASS or FAIL run of this check on this host that recorded
    an exact OS version. INTERRUPTED runs are never a baseline."""
    last = None
    try:
        # Binary mode: a line cut off inside a multibyte character (an append
        # interrupted by a crash) must be skipped, not abort the run.
        with open(state_dir / "history.jsonl", "rb") as f:
            for raw in f:
                try:
                    d = json.loads(raw.decode("utf-8"))
                except ValueError:  # includes UnicodeDecodeError
                    continue
                if (isinstance(d, dict) and d.get("name") == name and d.get("host") == host
                        and d.get("result") in (PASS, FAIL) and d.get("os_version")):
                    last = d
    except OSError:
        return None
    return last


def last_step_text(state: dict) -> str:
    last = state.get("last_completed_step")
    total = state.get("steps_expected")
    if not last:
        return "before step 1/%s" % total
    return 'after step %d/%s "%s"' % (last["index"], total, last["label"])


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) would terminate the process on Windows.
        import ctypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class NameLock:
    """Exclusive ownership of a check name. The lock is held by the kernel
    (LockFile via msvcrt on Windows, flock elsewhere) and released by the OS
    when the owner dies, so there is never a stale lock to reclaim."""

    def __init__(self, state_dir: Path, name: str):
        locks = state_dir / "locks"
        self.path = locks / (name + ".lock")
        self.owner_path = locks / (name + ".owner.json")
        self.f = None

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(str(self.path), "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.f = f
        return True

    def write_owner(self) -> None:
        write_json(self.owner_path, {"pid": os.getpid(), "host": socket.gethostname(), "since": now_iso()})

    def owner(self) -> dict:
        return read_json(self.owner_path) or {}

    def release(self) -> None:
        if not self.f:
            return
        try:
            os.remove(str(self.owner_path))
        except OSError:
            pass
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.f.close()
        self.f = None


def foreign_host(state: dict) -> bool:
    host = state.get("host")
    return bool(host) and host != socket.gethostname()


def _mark_interrupted(state_dir: Path, path: Path, state: dict) -> dict:
    state["result"] = INTERRUPTED
    state["reason"] = "runner ended without a result (killed, crashed or rebooted)"
    state["ended"] = state.get("updated") or now_iso()
    write_json(path, state)
    append_history(state_dir, state)
    print("DRAYL earlier run of %s was INTERRUPTED %s: %s" % (state.get("name"), last_step_text(state), state["reason"]),
          file=sys.stderr, flush=True)
    return state


def recover_stale(state_dir: Path, name: str, owned: bool = False):
    """A RUNNING state on this host whose name lock is free means its runner
    died (kill, crash, reboot): that run becomes INTERRUPTED instead of being
    forgotten. Runs from another host are left alone, they cannot be checked
    from here. owned=True: the caller already holds the name lock."""
    path = state_dir / "runs" / (name + ".json")
    state = read_json(path)
    if not state or state.get("result") != "RUNNING" or foreign_host(state):
        return None
    if owned:
        return _mark_interrupted(state_dir, path, state)
    lock = NameLock(state_dir, name)
    if not lock.try_acquire():
        return None
    try:
        # Re-read under the lock: a run may have finished in between.
        state = read_json(path)
        if not state or state.get("result") != "RUNNING" or foreign_host(state):
            return None
        return _mark_interrupted(state_dir, path, state)
    finally:
        lock.release()


# ---------------------------------------------------------------- watchers


class Watcher:
    """Reports physical (not synthetic) input. on_trip(reason) is called
    from the watcher thread; it must only set flags."""

    supported = False
    error = ""

    def __init__(self, on_trip, hands_off: bool, abort_key: str):
        self.on_trip = on_trip
        self.hands_off = hands_off
        self.abort_key = abort_key
        # Proof that the watcher was alive: a hands-off record should show
        # the synthetic events it saw, not just "no physical input".
        self.seen = {"synthetic": 0, "physical": 0}

    def start(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def _move(self) -> None:
        if self.hands_off:
            self.on_trip("physical mouse movement during a hands-off run")


class WindowsWatcher(Watcher):
    # LLKHF_INJECTED / LLMHF_INJECTED mark synthetic input (SendInput and
    # friends); events without the flag come from real hardware.
    VK = {"esc": 0x1B, "f12": 0x7B}
    tid = 0

    def start(self) -> bool:
        import ctypes
        from ctypes import wintypes

        self.ct, self.wt = ctypes, wintypes
        self.ready = threading.Event()
        self.ok = False
        self.tid = 0
        self.thread = threading.Thread(target=self._loop, name="drayl-input", daemon=True)
        self.thread.start()
        self.ready.wait(5)
        return self.ok

    def _loop(self) -> None:
        ct, wt = self.ct, self.wt
        user32 = ct.WinDLL("user32", use_last_error=True)
        kernel32 = ct.WinDLL("kernel32", use_last_error=True)
        LRESULT = ct.c_ssize_t
        PROC = ct.WINFUNCTYPE(LRESULT, ct.c_int, wt.WPARAM, wt.LPARAM)
        user32.SetWindowsHookExW.restype = wt.HHOOK
        user32.SetWindowsHookExW.argtypes = [ct.c_int, PROC, wt.HINSTANCE, wt.DWORD]
        user32.CallNextHookEx.restype = LRESULT
        user32.CallNextHookEx.argtypes = [wt.HHOOK, ct.c_int, wt.WPARAM, wt.LPARAM]
        user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
        user32.GetMessageW.argtypes = [ct.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        kernel32.GetModuleHandleW.restype = wt.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

        class KBD(ct.Structure):
            _fields_ = [("vk", wt.DWORD), ("scan", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD), ("extra", ct.c_size_t)]

        class MS(ct.Structure):
            _fields_ = [("pt", wt.POINT), ("data", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD), ("extra", ct.c_size_t)]

        abort_vk = self.VK.get(self.abort_key)

        def kbd(code, wparam, lparam):
            if code >= 0 and wparam in (0x100, 0x104):  # WM_KEYDOWN, WM_SYSKEYDOWN
                k = ct.cast(lparam, ct.POINTER(KBD)).contents
                self.seen["synthetic" if k.flags & 0x10 else "physical"] += 1
                if not k.flags & 0x10:
                    if abort_vk is not None and k.vk == abort_vk:
                        self.on_trip("abort key (%s) pressed" % self.abort_key)
                    elif self.hands_off:
                        self.on_trip("physical key press during a hands-off run")
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def mouse(code, wparam, lparam):
            if code >= 0:
                m = ct.cast(lparam, ct.POINTER(MS)).contents
                self.seen["synthetic" if m.flags & 0x01 else "physical"] += 1
                if not m.flags & 0x01:
                    if wparam == 0x200:  # WM_MOUSEMOVE
                        self._move()
                    elif self.hands_off and wparam in (0x201, 0x204, 0x207, 0x20A, 0x20B, 0x20E):
                        self.on_trip("physical mouse click or wheel during a hands-off run")
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._procs = (PROC(kbd), PROC(mouse))  # keep alive
        hmod = kernel32.GetModuleHandleW(None)
        hk = user32.SetWindowsHookExW(13, self._procs[0], hmod, 0)  # WH_KEYBOARD_LL
        hm = user32.SetWindowsHookExW(14, self._procs[1], hmod, 0) if self.hands_off else None  # WH_MOUSE_LL
        self.tid = kernel32.GetCurrentThreadId()
        if not hk or (self.hands_off and not hm):
            self.error = "SetWindowsHookExW failed (error %d)" % ct.get_last_error()
            self.ready.set()
            return
        self.ok = True
        self.ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ct.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(hk)
        if hm:
            user32.UnhookWindowsHookEx(hm)

    def stop(self) -> None:
        if self.tid:
            self.ct.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)  # WM_QUIT
            self.thread.join(2)


class MacWatcher(Watcher):
    # In a listen-only event tap, events posted by a process carry its pid in
    # kCGEventSourceUnixProcessID (field 41); hardware events carry 0.
    KEYCODE = {"esc": 53, "f12": 111}

    def start(self) -> bool:
        import ctypes
        import ctypes.util

        self.ct = ctypes
        self.ready = threading.Event()
        self.ok = False
        self.halt = False
        self.thread = threading.Thread(target=self._loop, name="drayl-input", daemon=True)
        self.thread.start()
        self.ready.wait(5)
        return self.ok

    def _loop(self) -> None:
        ct = self.ct
        cg = ct.CDLL(ct.util.find_library("ApplicationServices"))
        cf = ct.CDLL(ct.util.find_library("CoreFoundation"))
        CB = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_uint32, ct.c_void_p, ct.c_void_p)
        cg.CGEventTapCreate.restype = ct.c_void_p
        cg.CGEventTapCreate.argtypes = [ct.c_uint32, ct.c_uint32, ct.c_uint32, ct.c_uint64, CB, ct.c_void_p]
        cg.CGEventTapEnable.argtypes = [ct.c_void_p, ct.c_bool]
        cg.CGEventGetIntegerValueField.restype = ct.c_int64
        cg.CGEventGetIntegerValueField.argtypes = [ct.c_void_p, ct.c_uint32]
        cf.CFMachPortCreateRunLoopSource.restype = ct.c_void_p
        cf.CFMachPortCreateRunLoopSource.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_long]
        cf.CFRunLoopGetCurrent.restype = ct.c_void_p
        cf.CFRunLoopAddSource.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p]
        cf.CFRunLoopRunInMode.argtypes = [ct.c_void_p, ct.c_double, ct.c_bool]
        mode = ct.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode")
        abort_code = self.KEYCODE.get(self.abort_key)
        holder = {}

        def cb(proxy, typ, ev, ref):
            if typ in (0xFFFFFFFE, 0xFFFFFFFF):  # tap disabled by timeout / user input
                cg.CGEventTapEnable(holder["tap"], True)
                return ev
            if cg.CGEventGetIntegerValueField(ev, 41) != 0:
                self.seen["synthetic"] += 1
                return ev
            self.seen["physical"] += 1
            if typ == 12:  # modifier change (Shift, Cmd, ...)
                if self.hands_off:
                    self.on_trip("physical key press during a hands-off run")
            elif typ == 10:  # key down
                if abort_code is not None and cg.CGEventGetIntegerValueField(ev, 9) == abort_code:
                    self.on_trip("abort key (%s) pressed" % self.abort_key)
                elif self.hands_off:
                    self.on_trip("physical key press during a hands-off run")
            elif typ in (5, 6, 7, 27):  # moved / dragged
                self._move()
            elif self.hands_off and typ in (1, 3, 25, 22):  # buttons down, scroll
                self.on_trip("physical mouse click or wheel during a hands-off run")
            return ev

        self._cb = CB(cb)
        mask = (1 << 10)
        if self.hands_off:
            mask |= (1 << 1) | (1 << 3) | (1 << 25) | (1 << 22) | (1 << 5) | (1 << 6) | (1 << 7) | (1 << 27) | (1 << 12)
        tap = cg.CGEventTapCreate(1, 0, 1, mask, self._cb, None)  # session tap, head, listen-only
        if not tap:
            self.error = ("CGEventTapCreate failed: give the terminal app Input Monitoring "
                          "(System Settings > Privacy & Security > Input Monitoring)")
            self.ready.set()
            return
        holder["tap"] = tap
        src = cf.CFMachPortCreateRunLoopSource(None, tap, 0)
        cf.CFRunLoopAddSource(cf.CFRunLoopGetCurrent(), src, mode)
        cg.CGEventTapEnable(tap, True)
        self.ok = True
        self.ready.set()
        while not self.halt:
            cf.CFRunLoopRunInMode(mode, 0.2, False)

    def stop(self) -> None:
        self.halt = True
        if hasattr(self, "thread"):
            self.thread.join(2)


def make_watcher(on_trip, hands_off: bool, abort_key: str) -> Watcher:
    system = platform.system()
    if system == "Windows":
        return WindowsWatcher(on_trip, hands_off, abort_key)
    if system == "Darwin":
        return MacWatcher(on_trip, hands_off, abort_key)
    w = Watcher(on_trip, hands_off, abort_key)
    w.error = "physical input watching is not supported on %s" % system
    return w


# -------------------------------------------------------------------- run


class ProcessTree:
    """Owns every process the check starts, so cleanup does not depend on
    the leader still being alive. Windows: a job object (kill on close).
    POSIX: the child's own session / process group."""

    def __init__(self):
        self.job = None
        self.proc = None
        if os.name == "nt":
            self._make_job()

    def _make_job(self) -> None:
        import ctypes
        from ctypes import wintypes as wt

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wt.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        k.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        k.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
        nt = ctypes.WinDLL("ntdll")
        nt.NtResumeProcess.argtypes = [wt.HANDLE]
        self.k, self.nt, self.ct = k, nt, ctypes
        job = k.CreateJobObjectW(None, None)
        if not job:
            return
        info = EXTENDED()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.job = job

    def start(self, command, **kw) -> subprocess.Popen:
        if os.name != "nt":
            kw["start_new_session"] = True
            self.proc = subprocess.Popen(command, **kw)
            return self.proc
        if not self.job:
            raise OSError("cannot create a job object to contain the check's processes")
        # Start suspended and resume only after the job holds the process, so
        # nothing it spawns can escape cleanup.
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004  # CREATE_SUSPENDED
        proc = subprocess.Popen(command, **kw)
        if not self.k.AssignProcessToJobObject(self.job, int(proc._handle)):
            err = self.ct.get_last_error()
            proc.kill()
            proc.wait(5)
            raise OSError("cannot put the check into a job object (error %d)" % err)
        self.proc = proc
        if self.nt.NtResumeProcess(int(proc._handle)) != 0:
            self.kill()
            raise OSError("cannot resume the check process")
        return proc

    def kill(self) -> None:
        proc = self.proc
        if proc is None:
            return
        if os.name == "nt":
            self.k.TerminateJobObject(self.job, 1)
        else:
            pgid = proc.pid
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pgid = None
            if pgid is not None:
                for _ in range(30):
                    proc.poll()  # reap the leader so it does not keep the group alive as a zombie
                    try:
                        os.killpg(pgid, 0)
                    except (ProcessLookupError, PermissionError):
                        break
                    time.sleep(0.1)
                else:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def cmd_run(args) -> int:
    if not NAME_RE.match(args.name):
        print("drayl_check: --name must be letters, digits, '.', '_' or '-'", file=sys.stderr)
        return 2
    if not args.command:
        print("drayl_check: give the check command after --", file=sys.stderr)
        return 2
    state_dir = Path(args.state_dir)
    lock = NameLock(state_dir, args.name)
    if not lock.try_acquire():
        owner = lock.owner()
        print("drayl_check: %s is already running (host %s, pid %s)" % (args.name, owner.get("host"), owner.get("pid")),
              file=sys.stderr)
        return 2
    try:
        lock.write_owner()
        prev = read_json(state_dir / "runs" / (args.name + ".json"))
        if prev and prev.get("result") == "RUNNING" and foreign_host(prev):
            print("drayl_check: the last run of %s is still RUNNING on host %s; finish or check it there, or delete %s"
                  % (args.name, prev.get("host"), state_dir / "runs" / (args.name + ".json")), file=sys.stderr)
            return 2
        return _run_locked(args, state_dir)
    finally:
        lock.release()


def _run_locked(args, state_dir: Path) -> int:
    recover_stale(state_dir, args.name, owned=True)

    # One lock guards the run's control state: interruption, accepted steps
    # and the final verdict. on_trip does no I/O under it, so the input hook
    # callbacks stay fast. io_lock orders file writes so a late step write can
    # never overwrite the final result.
    lock = threading.RLock()
    io_lock = threading.Lock()
    ctl = {"trip": None, "final": False, "final_written": False}
    tripped = threading.Event()

    def on_trip(reason: str) -> None:
        with lock:
            if ctl["final"] or ctl["trip"]:
                return
            ctl["trip"] = reason
        tripped.set()

    watcher = make_watcher(on_trip, args.hands_off, args.abort_key)
    watching = watcher.start() if (args.hands_off or args.abort_key != "none") else False
    if args.hands_off and not watching:
        # Fail closed: a hands-off run that cannot see real input could turn
        # a touched run into a PASS.
        watcher.stop()
        print("drayl_check: cannot watch physical input: %s" % (watcher.error or "unsupported"), file=sys.stderr)
        return 2
    if args.abort_key != "none" and not watching:
        print("DRAYL note: abort key unavailable (%s); stop with Ctrl+C" % (watcher.error or "unsupported"), flush=True)

    path = state_dir / "runs" / (args.name + ".json")
    state = {
        "name": args.name,
        "result": "RUNNING",
        "reason": None,
        "command": args.command,
        "build": args.build or git_build(),
        "host": socket.gethostname(),
        "runner_pid": os.getpid(),
        "os": "%s %s" % (platform.system(), platform.release()),
        "os_version": os_version(),
        "os_changed_from": None,
        "hands_off": args.hands_off,
        "abort_key": args.abort_key if watching else "ctrl+c only",
        "timeout_s": args.timeout,
        "steps_expected": args.steps,
        "steps": [],
        "last_completed_step": None,
        "exit_code": None,
        "input_seen": None,
        "started": now_iso(),
        "updated": now_iso(),
        "ended": None,
    }
    prior = last_comparable_run(state_dir, args.name, state["host"])
    if prior and prior["os_version"] != state["os_version"]:
        state["os_changed_from"] = prior["os_version"]
        print("DRAYL note: OS changed since the last PASS/FAIL run of %s on this host (%s -> %s); "
              "do not compare this run with runs before the change"
              % (args.name, prior["os_version"], state["os_version"]), flush=True)
    write_json(path, state)

    def finish(result, reason, code) -> int:
        with lock:
            state.update(result=result, reason=reason, exit_code=code, ended=now_iso(), updated=now_iso(),
                         input_seen=dict(watcher.seen) if watching else None)
            snapshot = json.loads(json.dumps(state))
        with io_lock:
            write_json(path, snapshot)
            ctl["final_written"] = True
        append_history(state_dir, snapshot)
        n = len(snapshot["steps"])
        if result == PASS:
            print("DRAYL RESULT PASS %s %d/%d steps" % (args.name, n, args.steps), flush=True)
        elif result == FAIL:
            print("DRAYL RESULT FAIL %s: %s" % (args.name, reason), flush=True)
        else:
            print("DRAYL RESULT INTERRUPTED %s %s: %s" % (args.name, last_step_text(snapshot), reason), flush=True)
        print("DRAYL state %s" % path, flush=True)
        return EXIT[result]

    tree = ProcessTree()
    env = dict(os.environ, DRAYL_RUN_NAME=args.name, DRAYL_STATE_FILE=str(path.resolve()), PYTHONUNBUFFERED="1")
    try:
        proc = tree.start(args.command, stdout=subprocess.PIPE, stderr=None, stdin=subprocess.DEVNULL, env=env)
    except OSError as e:
        with lock:
            ctl["final"] = True
        watcher.stop()
        return finish(INTERRUPTED, "check did not start: %s" % e, None)

    def reader() -> None:
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            m = STEP_RE.match(line)
            if not m:
                continue
            with lock:
                # Nothing counts after an interruption or after the verdict.
                if ctl["trip"] or ctl["final"]:
                    continue
                step = {"index": len(state["steps"]) + 1, "label": m.group(2), "result": m.group(1),
                        "note": m.group(3), "at": now_iso()}
                state["steps"].append(step)
                state["last_completed_step"] = {"index": step["index"], "label": step["label"], "result": step["result"]}
                state["updated"] = step["at"]
                snapshot = json.loads(json.dumps(state))
            with io_lock:
                if not ctl["final_written"]:
                    write_json(path, snapshot)

    rt = threading.Thread(target=reader, name="drayl-reader", daemon=True)
    rt.start()

    prev_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda *_: on_trip("Ctrl+C"))
    deadline = time.monotonic() + args.timeout if args.timeout else None
    try:
        while proc.poll() is None and not tripped.is_set():
            if deadline and time.monotonic() > deadline:
                on_trip("timeout after %ds" % args.timeout)
                break
            time.sleep(0.05)
        if tripped.is_set():
            tree.kill()
        else:
            # The leader exited; give descendants that still hold stdout a
            # moment to finish their output, then clean up whatever is left.
            rt.join(2)
            tree.kill()
        rt.join(5)
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
    watcher.stop()

    with lock:
        ctl["final"] = True
        trip = ctl["trip"]
        steps = list(state["steps"])
    code = proc.returncode
    fails = [s for s in steps if s["result"] == FAIL]
    if fails:
        # A failed step is a verdict about the product; a later interruption
        # does not undo it.
        reason = 'step %d "%s" failed' % (fails[0]["index"], fails[0]["label"])
        if trip:
            reason += " (run then interrupted: %s)" % trip
        return finish(FAIL, reason, code)
    if trip:
        return finish(INTERRUPTED, trip, code)
    if code == 0 and len(steps) == args.steps:
        return finish(PASS, None, code)
    if len(steps) > args.steps:
        return finish(INTERRUPTED, "check reported %d steps, %d declared" % (len(steps), args.steps), code)
    return finish(INTERRUPTED, "check ended after %d of %d steps (exit code %s)" % (len(steps), args.steps, code), code)


def cmd_status(args) -> int:
    runs = Path(args.state_dir) / "runs"
    files = sorted(runs.glob("*.json")) if runs.is_dir() else []
    if args.name:
        files = [runs / (args.name + ".json")]
    shown = 0
    for p in files:
        if not p.exists():
            continue
        state = recover_stale(Path(args.state_dir), p.stem) or read_json(p)
        if not state:
            continue
        shown += 1
        if args.json:
            print(json.dumps(state, ensure_ascii=False))
            continue
        line = "%-24s %-11s build=%s ended=%s" % (state["name"], state["result"], state.get("build"), state.get("ended"))
        if state["result"] == INTERRUPTED:
            line += " %s: %s" % (last_step_text(state), state.get("reason"))
        elif state["result"] == FAIL:
            line += " %s" % state.get("reason")
        if state.get("os_changed_from"):
            line += " [OS changed: %s -> %s]" % (state["os_changed_from"], state.get("os_version"))
        print(line)
    if not shown and not args.json:
        print("no runs in %s" % runs)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="drayl_check", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a check: drayl_check run --name N --steps K [options] -- <command...>")
    r.add_argument("--name", required=True, help="stable check name; one state file per name")
    r.add_argument("--steps", required=True, type=int, help="number of steps the check must report")
    r.add_argument("--hands-off", action="store_true",
                   help="any physical key, click, wheel or mouse movement interrupts the run (checks that drive synthetic input)")
    r.add_argument("--abort-key", default="esc", choices=["esc", "f12", "none"],
                   help="physical key that interrupts the run (default esc)")
    r.add_argument("--timeout", type=int, default=0, help="seconds until the run counts as INTERRUPTED (0 = none)")
    r.add_argument("--build", help="build or commit under test (default: git rev-parse --short HEAD)")
    r.add_argument("--state-dir", default=".drayl", help="where run state lives (default .drayl)")
    r.add_argument("command", nargs=argparse.REMAINDER)
    s = sub.add_parser("status", help="show the last result of each check; reports stale runs as INTERRUPTED")
    s.add_argument("--name")
    s.add_argument("--json", action="store_true")
    s.add_argument("--state-dir", default=".drayl")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        if args.steps < 1:
            ap.error("--steps must be at least 1")
        return cmd_run(args)
    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
