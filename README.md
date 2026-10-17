# Drayl

Agent skills for the moment an AI coding agent says "done".

Agents are good at writing code and bad at knowing when the work is
finished. CI turns green while a review is still running. A review posts
findings five minutes after the agent reported success. A live test gets
interrupted halfway and the half-run is reported as a pass. Drayl gives
every agent in a repository the same, strict definition of done, and an
interview that adapts it to the project.

## What you get

Drayl does not make your agent write better code. It stops the agent from
saying "done" before the work is done, and from turning a half-finished
test into a pass.

| Without Drayl | With Drayl |
| --- | --- |
| CI turns green and the agent reports "done" while the review bot is still running or has already posted findings | Done means CI green on the **latest** commit, every review on that commit finished, every finding fixed or answered. No review after the wait: the agent reports BLOCKED, not done |
| The agent reads one place and misses findings | It reads all three places on GitHub: inline comments, review bodies, PR comments. No finding is skipped silently |
| No review bot means no review | A fresh subagent or a separate agent run reviews instead, or a person by hand. A self-review never counts |
| The agent merges too early, merges code it never checked, or tangles stacked PRs | It merges only if your policy allows, with a head guard (the merge fails if the PR changed after the check), lands stacked PRs in order, and confirms the change is really on the default branch |
| A live test is cut short by a timeout, a crash or someone touching the mouse, and the agent reports "works" | Every run ends with exactly one result: PASS, FAIL or INTERRUPTED. INTERRUPTED is never a pass and never a baseline, and the last completed step is saved |
| A test fails and the agent quietly changes the expectation | A FAIL stays a FAIL, gets a record and an issue |
| An OS update flips a test and nobody notices | Every run records the exact OS version with build and warns when it changed |

The rules land in your `AGENTS.md`, so every agent in the repository sees
them, even when no skill is loaded.

What one trial run showed (Droid and Codex, one throwaway repository
each, n = 1): Codex refused to merge while the configured review was
missing and reported BLOCKED, fixed the review finding, answered it in
the PR, and merged only after approval of exactly that commit. Droid
landed two stacked PRs in the right order. Given a deliberately wrong
expectation in a live check, Droid recorded FAIL and opened an issue
instead of changing the code to match. Both agents also broke a setup
rule, which led to fixes. Full record with versions and limits:
[docs/trials/2026-10-17-droid-codex.md](docs/trials/2026-10-17-droid-codex.md).

What Drayl does not do:

- It does not improve the code itself. It improves when the agent may
  say "done" and how honestly it reports results.
- It is instructions, not enforcement. An agent can still ignore them;
  report it and tighten the section.
- It costs waiting time: the agent waits for reviews instead of reporting
  early.
- GitHub with the `gh` CLI only. Real-input detection for hands-off runs
  on Windows and macOS only.
- It pays off when agents open, babysit or merge PRs, or run live checks.
  If you only let the agent write code and you merge yourself, you gain
  little.

## The skills

Three skills, one pack (1.1.2). Changes: [CHANGELOG.md](CHANGELOG.md).

| Skill | What it does |
| --- | --- |
| `drayl-setup` | Interviews you (at most eight questions, each with a recommended answer), detects the rest, shows what it will write, then writes a `Drayl` section into `AGENTS.md` and installs the skills |
| `drayl-pr` | Babysits a GitHub PR until CI is green on the latest head, every review on that head finished, and every finding is fixed or answered. Lands it only if your merge policy allows. No review bot? A fresh subagent or a separate agent run reviews instead, or a person by hand |
| `drayl-check` | Runs live checks (acceptance runs, dogfood, benchmarks, demos with synthetic input) so each run ends with exactly one result: PASS, FAIL or INTERRUPTED, and leaves a record |

Tried end to end with Droid and Codex. It is written for any agent that
reads `AGENTS.md` and the open `SKILL.md` format, so Claude Code (via
`CLAUDE.md` importing `AGENTS.md`), Cursor, Gemini CLI and others should
work too, but they have not been tried yet.

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

Each run records the exact OS version with build (for example
`Windows 11 25H2 10.0.26200.9711`, `macOS 26.6.2 (25G83)`, or
`Ubuntu 24.04.5 LTS (kernel 6.8.0-45-generic)`). An OS update can flip a
check without any change to your code, so when the OS changed since the
last PASS or FAIL run of the same check on that machine, the runner says
so and the older runs stop counting as a baseline. Drayl does not pin the
OS: your users get the updates too.

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

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | PASS |
| 1 | FAIL |
| 2 | Usage error, no result: bad arguments, a hands-off run that cannot watch real input, or the last run of this name still RUNNING on another host |
| 3 | INTERRUPTED |
| 4 | Lock collision: this check name is already running. No new result is written |

## Install

Requirements: Python 3.9 or newer for the runner (`python3` where `python`
is missing or is not Python 3), and the GitHub CLI `gh` 2.50 or newer,
logged in (`gh auth status`), for `drayl-pr`. Older `gh` versions lack
`gh pr checks --json`.

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

## Updating

Installed skills are a copy. To update them, either re-copy `skills/drayl-*`
over `.agents/skills/` (the same commands as Install; replace the three
folders) or re-run `drayl-setup`. A re-run shows the diff of the `AGENTS.md`
section and writes only after a yes, and it copies the skills again.

The pack version is `metadata.version` in the frontmatter of each
`SKILL.md`. What changed is in [CHANGELOG.md](CHANGELOG.md).

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
docs/trials/     records of trial runs with real agents
```

CI runs the unit tests on Linux, Windows and macOS with Python 3.9 and
the latest Python 3.

## License

MIT, see [LICENSE](LICENSE).
