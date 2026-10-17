"""Example hands-off check: drives synthetic input and reports steps.

    python skills/drayl-check/scripts/drayl_check.py run --name synthetic-demo \
        --steps 3 --hands-off -- python examples/synthetic_input_check.py

Its own synthetic mouse moves and Shift presses must not interrupt the run;
touching the real mouse or keyboard while it runs must (INTERRUPTED).
Windows and macOS. On Linux it exits 2 with a message and does not drive
input. Moves the cursor by 1 px back and forth, presses Shift.
"""
import ctypes
import ctypes.util
import platform
import sys
import time

SECONDS_PER_STEP = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0


def windows_driver():
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]

    class U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", U)]

    send = ctypes.windll.user32.SendInput

    def move(dx):
        i = INPUT(type=0)
        i.u.mi = MOUSEINPUT(dx, 0, 0, 0x0001, 0, 0)  # MOUSEEVENTF_MOVE
        send(1, ctypes.byref(i), ctypes.sizeof(INPUT))

    def shift():
        for flags in (0, 0x0002):  # down, KEYEVENTF_KEYUP
            i = INPUT(type=1)
            i.u.ki = KEYBDINPUT(0x10, 0, flags, 0, 0)
            send(1, ctypes.byref(i), ctypes.sizeof(INPUT))

    return move, shift


def mac_driver():
    cg = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))

    class P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    cg.CGEventCreate.restype = ctypes.c_void_p
    cg.CGEventCreate.argtypes = [ctypes.c_void_p]
    cg.CGEventGetLocation.restype = P
    cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, P, ctypes.c_uint32]
    cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]

    def move(dx):
        loc = cg.CGEventGetLocation(cg.CGEventCreate(None))
        cg.CGEventPost(0, cg.CGEventCreateMouseEvent(None, 5, P(loc.x + dx, loc.y), 0))

    def shift():
        for down in (True, False):
            cg.CGEventPost(0, cg.CGEventCreateKeyboardEvent(None, 56, down))

    return move, shift


def main():
    system = platform.system()
    if system == "Windows":
        move, shift = windows_driver()
    elif system == "Darwin":
        move, shift = mac_driver()
    else:
        print("synthetic_input_check: hands-off synthetic input is Windows and macOS only (this is %s)" % system,
              file=sys.stderr)
        return 2
    for step in ("mouse jiggle", "shift presses", "mixed"):
        end = time.time() + SECONDS_PER_STEP
        dx = 1
        while time.time() < end:
            if step != "shift presses":
                move(dx)
                dx = -dx
            if step != "mouse jiggle":
                shift()
            time.sleep(0.05)
        print("DRAYL-STEP PASS %s" % step, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
