# Changelog

## 1.1.1

- Linux `os_version` is the distro from `/etc/os-release` plus the kernel
  (`Ubuntu 24.04.5 LTS (kernel 6.8.0-45-generic)`). 1.1.0 stored only
  `Linux <kernel>`, so the first run of a check after this update may
  print `OS changed` once.
- A Ctrl+C during cleanup still leaves PASS, FAIL or INTERRUPTED on disk.
  The runner restores the default signal handler only after that write.
- Concurrent checks append `history.jsonl` under one lock, so a torn line
  cannot hide the OS version the next run compares against.
- A check that reports every declared step and then exits non-zero is
  INTERRUPTED, with a reason that says so.
- `--timeout` below 0 is a usage error and does not start a run.
- `examples/synthetic_input_check.py` exits 2 on Linux instead of calling
  the macOS driver.
- `drayl-setup` replaces the whole Drayl section, markers included, so a
  re-run does not nest `<!-- drayl:begin` inside itself.

`drayl-pr` is unchanged. Its version matches the pack.

## 1.1.0

First tagged release.

- Each live check records the exact OS build and warns when it changed
  since the last PASS or FAIL run of the same check on that machine.
- Setup never writes without a yes, including non-interactive runs, and
  never fills in an answer silently.
- Review without subagents: a separate read-only agent run, or a person
  reviewing by hand (`Drayl review (manual) on <sha>`).
- `drayl-pr` and `drayl-check` work without a Drayl section, using the
  defaults listed in each skill.
- New setup question for posting PR comments and opening issues.
- `drayl-setup` is self-contained.
- CI runs the unit tests on Linux, Windows and macOS with Python 3.9 and
  the latest Python 3.
