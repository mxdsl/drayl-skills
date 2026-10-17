---
name: drayl-setup
description: Set up or update the Drayl workflow (drayl-pr and drayl-check) for this repository through a short interview - detect what can be detected, ask at most eight questions, show the result, and write the Drayl section into AGENTS.md only after the user confirms. Use when the user says "drayl setup", wants to install or adapt Drayl, or when another Drayl skill finds no Drayl section in AGENTS.md.
license: MIT
metadata:
  pack: drayl
  version: 1.0.0
---

# Drayl setup: an interview, then one reviewed write

Goal: the repository gets a `Drayl` section in `AGENTS.md` that tells every
agent when work is done, plus the Drayl skills in a place each agent finds.
The interview only fills in project values. The core rules of `drayl-pr`
and `drayl-check` are fixed and are not asked about.

Talk to the user in their language. Write the files in English unless the
user asks otherwise.

## 1. Say what will happen

Tell the user in two or three sentences: you will look around the repo,
ask up to eight short questions with a recommended answer each, show
everything you are going to write, and write nothing before they say yes.

## 2. Detect before you ask

Find out yourself, read-only:

| What | How |
| --- | --- |
| GitHub repo and default branch | `gh repo view --json nameWithOwner,defaultBranchRef`; `gh auth status` |
| CI | `.github/workflows/*.yml`; on a recent PR `gh pr checks <n> --json name,bucket`; required checks via `gh api repos/<repo>/branches/<default>/protection` (may be 404 or forbidden: then "unknown") |
| Review bots | authors of reviews and comments on the last 10 PRs: `gh pr list -R <repo> --state all --limit 10 --json number`, then `gh api repos/<repo>/pulls/<n>/reviews --jq '.[].user.login'` and `.../comments`; logins ending in `[bot]` |
| Stacked PRs | last 20 PRs whose `baseRefName` is not the default branch |
| Merge method | repo settings: `gh repo view --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed` |
| Pre-push commands | `package.json` scripts, `Makefile`, `go.mod`, `pyproject.toml`, `Cargo.toml`, existing `AGENTS.md`/`CONTRIBUTING.md`, CI steps |
| Agents in use | `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.factory/`, `.cursor/`, `.codex/`, `.gemini/`, `.github/copilot-instructions.md`, `.agents/` |
| Existing Drayl section | `<!-- drayl:begin` in `AGENTS.md` |
| Live checks | folders or scripts named like acceptance, e2e, smoke, bench, dogfood, demo; UI automation tools |
| Python 3.9+ | `python3 --version` or `python --version` (or `py -3` on Windows); needed by `drayl_check.py` |

If something cannot be detected, it becomes a question or a stated default.
If `gh` is missing or not logged in, say so: `drayl-pr` needs it.

## 3. The interview

Ask only what detection could not answer. At most eight questions, in two
or three rounds. Every question has a recommended answer, marked, so the
user can reply "ok" or with numbers like `1b 2a 3a`. Use your question tool
if you have one and it works; otherwise ask in chat with numbered options.

1. **Merge policy**: who may merge?
   a) nobody but the user (agent stops at DONE) - recommended
   b) the agent, after the user approves the current head
   c) the agent, automatically when DONE
2. **Reviewers**: show what you detected. Use them? If none: fresh subagent
   review (recommended) or none. Review wait before BLOCKED: 10 minutes
   (recommended) or another value.
3. **Required checks**: show the detected checks. All checks on the PR
   (recommended if branch protection is unknown), only required ones, or a
   list.
4. **Stacked PRs**: show what you detected. Does the project use them?
5. **Before every push**: show the detected build, test and lint commands.
   Keep, change, add?
6. **Live checks**: does the project have checks against a real running
   system, hardware or UI, or measurements? If yes: does any of them drive
   synthetic mouse or keyboard input (then hands-off), and which abort key
   (Esc recommended)?
7. **Records and evidence** (only if 6 is yes): records folder in the repo
   (recommended `docs/records/`) and raw evidence folder outside the repo
   (recommended `~/drayl-evidence/`).
8. **Reports**: language and length of the agent's DONE/BLOCKED reports.

Do not ask about the fixed rules. If the user wants to change one, explain
why it exists (see the README section "Why these rules") and, if they
still want it, write their exception into the section as an explicit
project rule, so it is visible.

## 4. Show everything before writing

Fill `templates/agents-section.md` (next to this file) with the answers and
show the user:

- the complete section as it will appear in `AGENTS.md`;
- every file you will create or change (see step 5);
- for a re-run: a diff of the old and the new section.

Ask: write it? Change something? Write only after a clear yes.

## 5. Write

1. `AGENTS.md`: replace everything between `<!-- drayl:begin` and
   `<!-- drayl:end -->`, or append the section if there is none. Create
   `AGENTS.md` if it does not exist. Touch nothing outside the markers.
2. Skills: copy the three folders `drayl-setup`, `drayl-pr`, `drayl-check`
   from the Drayl source (the folder this skill was loaded from, or a clone
   of the Drayl repository) to `.agents/skills/`. Keep `scripts/` and
   `templates/`.
3. Agents that do not read `.agents/skills/`: give each one a stub in its
   own skills folder, for example `.claude/skills/<skill>/SKILL.md` for
   Claude Code:

   ```markdown
   ---
   name: <skill>
   description: <same description as the original>
   ---
   Read and follow `.agents/skills/<skill>/SKILL.md`. Change the procedure
   there, never in this stub.
   ```

   Which agents need a stub is listed in the README table "Where agents
   look for skills". When in doubt, check the agent's documentation; a
   stub never hurts.
4. `CLAUDE.md`: if Claude Code is used and `CLAUDE.md` does not import
   `AGENTS.md`, add the line `@AGENTS.md` (keep any existing content).
5. `.gitignore`: add `.drayl/` (runner state is local).
6. If live checks are on: create the records folder with a short README
   pointing to `.agents/skills/drayl-check/templates/record.md`.

## 6. Verify

- Run the runner self-test and show the output; it must end with
  `DRAYL RESULT PASS drayl-selftest 1/1 steps`:

  ```bash
  python .agents/skills/drayl-check/scripts/drayl_check.py run --name drayl-selftest --steps 1 --abort-key none -- python -c "print('DRAYL-STEP PASS selftest')"
  ```

  (`py -3` instead of `python` on Windows if needed.)
- `gh auth status` succeeds.
- Re-read the written section from disk and confirm it matches what the
  user approved.

## 7. Offer the next step

Offer to commit the change on a new branch and open a PR. If the user
agrees, babysit that PR with `drayl-pr`: the setup is the first PR that
goes through the new rules.

## Re-running setup

A re-run starts at step 2 with the existing section as the default
answers. Ask only about what changed or what the user wants to change.
Never overwrite the section without showing the diff first.
