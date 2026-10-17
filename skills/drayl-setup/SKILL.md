---
name: drayl-setup
description: Set up or update the Drayl workflow (drayl-pr and drayl-check) for this repository through a short interview - detect what can be detected, ask at most eight questions, show the result, and write the Drayl section into AGENTS.md only after the user confirms. Use when the user says "drayl setup", wants to install or adapt Drayl, or when another Drayl skill finds no Drayl section in AGENTS.md.
license: MIT
metadata:
  pack: drayl
  version: 1.1.2
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
If `gh` is missing, older than 2.50 (`gh --version`; older versions lack
`gh pr checks --json`) or not logged in, say so: `drayl-pr` needs it.

## 3. The interview

Ask only what detection could not answer. At most eight questions, in two
or three rounds. Every question has a recommended answer, marked, so the
user can reply "ok" or with numbers like `1b 2a 3a`. Use your question tool
if you have one and it works; otherwise ask in chat with numbered options.

Never fill in an answer silently. Every value detection could not settle
is either asked or listed as "recommended, change if needed" in the
message the user approves. To save a round, you may send the questions
together with the draft from step 4 built from the recommended answers.

1. **Merge policy**: who may merge?
   a) nobody but the user (agent stops at DONE) - recommended
   b) the agent, after the user approves the current head
   c) the agent, automatically when DONE
2. **Reviewers**: show what you detected. Use them? If none: fresh
   independent review by a subagent or a separate agent run (recommended,
   see `drayl-pr`), or a person who reviews by hand. Review wait before
   BLOCKED: 10 minutes (recommended) or another value. If your own
   instructions forbid subagents, say so and offer the other two.
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
8. **GitHub posts and reports**: may the agent post without asking
   a) PR comments and thread replies on its own PRs (answers to review
   findings, the fresh review) - recommended yes;
   b) new issues (a FAIL in a live check, a finding outside the PR) -
   recommended ask first?
   And the language and length of the DONE/BLOCKED reports.

Do not ask about the fixed rules. If the user wants to change one, explain
why it exists and, if they still want it, write their exception into the
section as an explicit project rule, so it is visible. Why each rule
exists:

- **Done means the latest head.** CI and reviews on an older commit say
  nothing about the code that will land.
- **Wait for the review, then read three places.** Review bots often
  report "passed" while posting findings, in inline comments, review
  bodies and top-level comments. A review that never arrives on the
  latest head is BLOCKED, not done.
- **Answer every finding in its thread.** A silently skipped finding looks
  exactly like an overlooked one.
- **Never force-push; never merge a stacked child into its parent.**
  Force-pushes destroy reviewed history; a child merged into its parent
  looks merged and lands nowhere.
- **INTERRUPTED is its own result.** Without it, a half-finished live run
  quietly becomes a pass, or a "regression" that sends someone hunting a
  bug that does not exist.

## 4. Show everything before writing

Fill `templates/agents-section.md` (next to this file) with the answers
(with live checks `no`, drop the four lines under it) and show the user:

- the complete section as it will appear in `AGENTS.md`;
- every file you will create or change (see step 5);
- for a re-run: a diff of the old and the new section.

Ask: write it? Change something? Write only after a clear yes.

If no answer can come in this session (a non-interactive run such as
`droid exec` or `codex exec` without a user), stop here: show the draft,
say that it needs a yes, and write nothing. A request to "set up Drayl" is
not the yes; the yes is to the shown draft.

## 5. Write

1. `AGENTS.md`: the filled template includes its `<!-- drayl:begin` and
   `<!-- drayl:end -->` lines. If those markers are already in `AGENTS.md`,
   replace from the begin line through the end line with the filled
   template. If they are not, append the filled template. Create
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

   Droid, Codex, Cursor and Gemini CLI read `.agents/skills/` themselves;
   do not give them a stub, or the skill shows up twice. Claude Code does
   not and needs the stub. For any other agent, check its documentation
   first.
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

  (`python3` where `python` is missing or is not Python 3; `py -3` on
  Windows if needed.)
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
