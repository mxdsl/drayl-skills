# Drayl

Agent skills for the moment an AI coding agent says "done".

Agents are good at writing code and bad at knowing when the work is
finished. CI turns green while a review is still running. A review posts
findings five minutes after the agent reported success. A live test gets
interrupted halfway and the half-run is reported as a pass. Drayl gives
every agent in a repository the same, strict definition of done, and an
interview that adapts it to the project.

Three skills, one pack:

| Skill | What it does |
| --- | --- |
| `drayl-setup` | Interviews you (at most eight questions, each with a recommended answer), detects the rest, shows what it will write, then writes a `Drayl` section into `AGENTS.md` and installs the skills |
| `drayl-pr` | Babysits a GitHub PR until CI is green on the latest head, every review on that head finished, and every finding is fixed or answered. Lands it only if your merge policy allows. No review bot? A fresh subagent reviews instead |
| `drayl-check` | Runs live checks (acceptance runs, dogfood, benchmarks, demos with synthetic input) so each run ends with exactly one result: PASS, FAIL or INTERRUPTED, and leaves a record |

Works with any agent that reads `AGENTS.md` and the open `SKILL.md`
format: Droid, Claude Code (via `CLAUDE.md` importing `AGENTS.md`), Codex,
Cursor, Gemini CLI, Copilot and others.

## PASS, FAIL, INTERRUPTED

| Result | Meaning |
| --- | --- |
| PASS | Every declared step passed and the check exited cleanly |
| FAIL | A step failed: the product is wrong |
| INTERRUPTED | The run did not finish (abort key, a real key press or mouse movement during a hands-off run, Ctrl+C, timeout, crash, missing steps). The measurement is invalid: never a pass, never a regression, never a baseline. Re-run it |

The runner (`skills/drayl-check/scripts/drayl_check.py`, Python 3.9+,
standard library only) wraps any check command. The check prints
`DRAYL-STEP PASS <label>` or `DRAYL-STEP FAIL <label>` after each step; the
runner saves the state after every step, so an interrupted run always
names its last completed step. If the runner itself is killed, the next
`status` reports that run as INTERRUPTED instead of forgetting it.

```bash
python skills/drayl-check/scripts/drayl_check.py run --name resize --steps 5 --hands-off -- ./check-resize.sh
# ...
# DRAYL RESULT INTERRUPTED resize after step 3/5 "drag corner": physical mouse movement during a hands-off run
```

`--hands-off` is for checks that drive synthetic mouse or keyboard input.
The runner tells real input from synthetic input (Windows: the injected
flag on low-level hooks; macOS: the posting process id in an event tap)
and interrupts the run on real input only. It refuses to start a
hands-off run if it cannot watch real input. Linux is not supported for
hands-off runs yet.

## Install

1. Get the skills into your repository:

   ```bash
   git clone --depth 1 https://github.com/mxdsl/drayl-skills /tmp/drayl
   mkdir -p .agents/skills
   cp -r /tmp/drayl/skills/drayl-* .agents/skills/
   ```

   PowerShell:

   ```powershell
   git clone --depth 1 https://github.com/mxdsl/drayl-skills $env:TEMP\drayl
   New-Item -ItemType Directory -Force .agents\skills | Out-Null
   Copy-Item -Recurse $env:TEMP\drayl\skills\drayl-* .agents\skills\
   ```

2. Ask your agent: **"run drayl-setup"**. If your agent does not see
   skills in `.agents/skills/` yet (Claude Code, for example), say
   "read `.agents/skills/drayl-setup/SKILL.md` and follow it". Setup adds
   the stubs so it finds them next time.

3. Answer the questions. Setup shows the full `AGENTS.md` section and
   every file before it writes anything.

From then on, `drayl-pr` and `drayl-check` load when the agent works on a
PR or runs a live check, and the `AGENTS.md` section reminds every agent
of the rules even when no skill is loaded.

### Where agents look for skills

| Agent | Reads `.agents/skills/` | Otherwise |
| --- | --- | --- |
| Droid (Factory) | yes (documented and tested) | `.factory/skills/` |
| Claude Code | no | stub in `.claude/skills/<skill>/SKILL.md` |
| Codex | yes (tested with codex-cli 0.153) | |
| Cursor | yes (documented) | `.cursor/skills/` |
| Gemini CLI | yes (documented) | `.gemini/skills/` |

`drayl-setup` writes a stub for every agent in use that does not read
`.agents/skills/`. A stub only points to the real skill, so there is one
copy to maintain.

## Why these rules

Every fixed rule exists because its absence went wrong in real work:

- **Done means the latest head.** CI and reviews on an older commit say
  nothing about the code that will land.
- **Wait for the review, then read three places.** Review bots often
  report "passed" while posting findings, and they post in three places:
  inline comments, review bodies, and top-level comments. A review that
  never arrives on the latest head is BLOCKED, not done.
- **Answer every finding in its thread.** A silently skipped finding looks
  exactly like an overlooked one.
- **Never merge a stacked child into its parent.** It looks merged and
  lands nowhere: the change has to be landed again.
- **INTERRUPTED is its own result.** Without it, a half-finished live run
  quietly becomes a pass, or a "regression" that sends someone hunting a
  bug that does not exist.
- **Fail closed.** A hands-off run that cannot see real input could turn a
  touched run into a pass, so it does not start.

## Repository layout

```text
skills/
  drayl-setup/   SKILL.md, templates/agents-section.md
  drayl-pr/      SKILL.md
  drayl-check/   SKILL.md, scripts/drayl_check.py, templates/record.md
examples/        synthetic_input_check.py (hands-off demo for Windows and macOS)
tests/           unit tests for the runner: python -m unittest discover -s tests
```

## License

MIT, see [LICENSE](LICENSE).
