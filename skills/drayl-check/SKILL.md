---
name: drayl-check
description: Run a live check (acceptance run, dogfood, benchmark, demo, anything against a real running system, real hardware or a real UI) so it ends with exactly one honest result - PASS, FAIL or INTERRUPTED - and leaves a record. Use before running, re-running or reporting any live check or measurement, and before comparing results across runs. Not for unit tests or CI.
license: MIT
metadata:
  pack: drayl
  version: 1.0.0
---

# Live checks with one honest result

A live check runs against something real: a running app, a device, a UI, a
network, a measurement. These runs get interrupted - someone touches the
mouse, presses a key, a connection drops, the laptop sleeps. An unfinished
run must never turn into a pass, and never into a regression.

Project settings (records folder, evidence folder, abort key) are in the
`Drayl` section of `AGENTS.md`. If that section is missing, run the
`drayl-setup` skill first or use the defaults below.

## The three results

| Result | Meaning | What you do with it |
| --- | --- | --- |
| PASS | Every declared step reported PASS and the check exited 0 | Report it, write the record |
| FAIL | At least one step reported FAIL | The product is wrong: report it, open an issue, write the record |
| INTERRUPTED | The run did not finish: abort key, physical input during a hands-off run, Ctrl+C, timeout, crash, lost connection, missing steps | The measurement is invalid. Re-run it. Never count it as a pass, a fail, a regression or a baseline |

FAIL is a statement about the product. INTERRUPTED is a statement about the
measurement. Do not mix them up: a check script that crashes is INTERRUPTED,
not FAIL, unless a step already reported FAIL.

## Run every live check through the runner

The runner is `scripts/drayl_check.py` next to this file (Python 3.9+,
standard library only, Windows, macOS, Linux). With the default install
that is `.agents/skills/drayl-check/scripts/drayl_check.py`.

1. Look for unfinished runs first:

   ```bash
   python .agents/skills/drayl-check/scripts/drayl_check.py status
   ```

   A run whose runner died (kill, crash, reboot) shows up here as
   INTERRUPTED with its last completed step. Report it; do not ignore it.

2. Make the check report its steps. Any language works. After each
   finished step the check prints one line to stdout and flushes:

   ```text
   DRAYL-STEP PASS <label> [-- note]
   DRAYL-STEP FAIL <label> [-- note]
   ```

   Example notes: `-- 73 ms`, `-- 1500 ms > limit 1000 ms`. Other output is
   passed through unchanged.

3. Run it through the runner with the number of steps it must report:

   ```bash
   python .agents/skills/drayl-check/scripts/drayl_check.py run \
     --name window-resize --steps 5 [--hands-off] [--timeout 300] \
     -- <command that runs the check>
   ```

   - `--name`: stable name, one state file per check.
   - `--steps`: how many steps a complete run reports. Fewer steps means
     INTERRUPTED, never PASS.
   - `--hands-off`: the check drives synthetic mouse or keyboard input
     (SendInput, CGEventPost, UI automation). The first real key press,
     click, wheel or mouse movement interrupts the run.
     The runner refuses to start a hands-off run if it cannot watch real
     input (it fails closed).
   - `--abort-key esc|f12|none`: physical key that stops the run
     (default `esc`). Ctrl+C in the runner's terminal always works.
   - `--timeout`: seconds until the run counts as INTERRUPTED.
   - `--build`: what is under test; defaults to the git commit
     (`-dirty` if tracked files changed).

4. Read the last line: `DRAYL RESULT PASS|FAIL|INTERRUPTED ...`. Exit
   codes: 0 PASS, 1 FAIL, 3 INTERRUPTED, 2 usage error (no result).

The runner writes `.drayl/runs/<name>.json` after every step and appends
each final result to `.drayl/history.jsonl`. Keep `.drayl/` out of git.

Other runner behavior worth knowing:

- One run per name at a time. A second run with the same name is refused
  while the first runner is alive (an OS file lock on
  `.drayl/locks/<name>.lock`, released by the OS if the runner dies).
- A RUNNING state written on another host is never touched from here;
  the runner refuses to start that check until it is resolved on that
  host or the state file is deleted.
- After the run, the runner stops every process the check started (a job
  object on Windows, the process group elsewhere). Start services that
  must keep running outside the check.
- After an interruption, steps the check still prints are ignored.
- A FAIL stays FAIL even if the run is interrupted afterwards.

### How real input is told apart from synthetic input

- Windows: low-level keyboard and mouse hooks; events without the
  `LLKHF_INJECTED` / `LLMHF_INJECTED` flag come from hardware.
- macOS: a listen-only event tap; synthetic events carry the posting
  process id, hardware events carry 0. The terminal app needs Input
  Monitoring (System Settings > Privacy & Security).
- Linux: not supported yet. Hands-off runs refuse to start; the abort key
  falls back to Ctrl+C.
- Input injected by other tools (remote desktop helpers, macro tools)
  counts as synthetic and is not detected.
- The final state lists `input_seen` (synthetic and physical counts). A
  hands-off record should show synthetic events > 0; that proves the
  watcher was alive.

## Rules

1. Every live check that produces a verdict runs through the runner. A
   result typed by hand into a chat or a doc is not a result.
2. INTERRUPTED is re-run from the start. There is no resume: the system
   under test may have changed while the run was stopped.
3. Compare only PASS and FAIL runs of the same check, the same number of
   steps and a known build. Never compare against an INTERRUPTED run, and
   never use one as the "before" of a before/after.
4. Report the result exactly as the runner printed it, including the last
   completed step and the reason for INTERRUPTED. Do not soften it.
5. A FAIL gets an issue before the round is reported done.
6. Do not touch the machine during a hands-off run. If you are the agent
   and the user is at the machine, tell them before you start and how long
   it takes.

## Record every run that counts

Each PASS or FAIL that someone will rely on gets a record, and so does an
INTERRUPTED run if it is reported. Use `templates/record.md` next to this
file and put it where the `Drayl` section says (default
`docs/records/<date>-<check>.md`). A record states: date, build on every
device, devices and OS versions, setup, the exact command, the numbers
with n, the result, everything that did not match, and honest limits.

Raw evidence (logs, screenshots, videos, state JSON) stays outside the
repo in the evidence folder from the `Drayl` section, with a short README.
Never store clipboard contents, personal data, tokens or keys there, and
check screenshots and videos for private content before sharing them.
