# Trial run: Droid and Codex - 2026-10-17

One trial per agent, to see whether the skills work outside the repository
they came from. This is a small, honest sample, not a benchmark.

## Setup

- **Drayl version:** skills 1.0.0 (commit `0b992f0` of this repository),
  installed as the README describes, into `.agents/skills/`.
- **Agents:** Droid CLI 0.223.0 (`droid exec`, each user turn resumed the
  same session) and Codex CLI 0.153.4 (`codex exec` / `codex exec resume`,
  model `gpt-6-astra`, reasoning `xhigh`). Both ran non-interactively.
  The Codex install had a global `AGENTS.md` that forbids subagents.
- **Repositories:** two private throwaway GitHub repositories, one per
  agent, each with a tiny Python calculator, unit tests and a GitHub
  Actions workflow. They were deleted after the trial, so there are no
  links.
- **The user:** the maintainer's own agent played the user and the human
  reviewer, with the same task texts for both agents.
- **Machine:** Windows 11 (10.0.26200), GitHub CLI 2.92.0.

## What happened

| Step | Droid | Codex |
| --- | --- | --- |
| "Set up Drayl for this repo" | Wrote the `AGENTS.md` section without showing it and waiting for a yes. **Violation of the skill.** | Showed the draft and waited, but filled in the recommended answers without saying so. **Violation of the skill.** |
| Setup PR with `drayl-pr` | CI green, fresh-subagent review posted, merged automatically as configured | No subagents allowed and no review bot: waited 10 minutes and reported **BLOCKED** (review missing on the latest head). After a manual review with one finding: fixed it, answered it in the PR, merged only after approval of exactly the new head |
| Two stacked PRs (`mul`, then `div` on top) | Merged the parent, retargeted the child to `main`, merged `main` into it, reviewed the new head, merged | Merged the parent, retargeted the child, fixed a review finding on it (traceback on non-numeric input). Then hit its usage limit before merging the child |
| Live check with `drayl-check` | Step 3 had a deliberately wrong expectation (`0.333` for `1/3`). Recorded **FAIL**, left the calculator unchanged, opened an issue. A second run that ran into `--timeout` was recorded as **INTERRUPTED**, not as a pass or fail. The record landed through a PR | Not run (usage limit) |

## Changes made because of this trial

Released in `34e616a`:

- `drayl-setup` never writes without a yes to the shown draft, also in
  non-interactive runs, and never fills in an answer silently.
- Review without subagents: a separate read-only agent run, or a person
  reviewing by hand with `Drayl review (manual) on <sha>`.

## Limits

- n = 1 per agent, one machine, one tiny project. Claude Code, Cursor and
  Gemini CLI were not tried.
- The human side was simulated by an agent. It made one mistake of its
  own: a manual review that named a wrong commit SHA, deleted within a
  minute and posted again with the right one.
- No review bot ran on these repositories; only the fresh-subagent and
  manual review paths were exercised.
- Hands-off live checks (synthetic input) were not part of this trial.
  They were tested separately on Windows 11 and macOS 26.6.2, where real
  mouse and keyboard input during a run was detected and recorded as
  INTERRUPTED.
