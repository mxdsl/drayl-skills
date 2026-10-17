<!-- drayl:begin v1 -->
## Drayl: when work is done

Written by `drayl-setup` on <YYYY-MM-DD>. Change it by running `drayl-setup`
again or by editing the values below. Procedures: `.agents/skills/drayl-pr/`
and `.agents/skills/drayl-check/`.

### Fixed rules

- A PR is done only when CI is green on the latest head, every review on
  that head has finished, and every finding is fixed or answered in its
  thread. A review missing on the latest head after the review wait means
  BLOCKED, not done.
- Live checks end with exactly one result: PASS, FAIL or INTERRUPTED. An
  INTERRUPTED run is never a pass, never a regression and never a
  baseline; it is re-run. Every live check runs through `drayl_check.py`.
- Never force-push. Never merge a stacked child into its parent branch.
- Report what was checked. Never report done on an older head, an older
  review or a check status alone.

### Project values

- **Repository:** <owner/name> on GitHub, default branch `<main>`
- **Merge:** <never - the user merges | after <name> approves the current head | automatically when done>; method `<squash|merge|rebase>`
- **Required CI checks:** <all checks on the PR | only required checks | list: `a`, `b`>
- **Reviewers:** <Name (check `x`, author `bot[bot]`) | fresh independent review (subagent or separate agent run) | <person> by hand, comment `Drayl review (manual) on <sha>`>
- **Review wait:** <10> minutes, then BLOCKED
- **Stacked PRs:** <yes | no>
- **Before every push:**
  - `<command>`
- **Live checks:** <no | yes>
  - Runner: `python .agents/skills/drayl-check/scripts/drayl_check.py`
  - Abort key: <esc>; hands-off for checks that drive synthetic input: <yes | no>
  - Records: `<docs/records/>`
  - Raw evidence (outside the repo): `<~/drayl-evidence/>`
- **Reports:** <language>, <short | detailed>

### Project exceptions

<None. If the user overrides a fixed rule, write it here with the reason.>
<!-- drayl:end -->
