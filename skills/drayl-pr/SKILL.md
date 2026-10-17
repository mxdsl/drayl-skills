---
name: drayl-pr
description: Babysit your own GitHub pull request until it is genuinely done - CI green on the latest head, every review on that head finished, and every review finding fixed or answered in its thread - then land it only if the project's merge policy allows. Use after opening or pushing to a PR, when asked to watch CI or reviews, and before reporting a PR as done or merging it. Not for opening PRs.
license: MIT
metadata:
  pack: drayl
  version: 1.0.0
---

# A PR is not done when CI turns green

It is done when CI is green on the latest head, every review that started
on that head has finished, and no finding is left unanswered. The agent
that pushed the PR babysits it to the end.

Project settings are in the `Drayl` section of `AGENTS.md`: merge policy,
required checks, reviewers, review wait, stacked PRs, commands before
push, report language. If the section is missing, run `drayl-setup` first.
Without it, use the defaults: never merge, all checks required, fresh
independent review, 10 minutes review wait.

Below, `<repo>` is `owner/name` and `<n>` is the PR number. Pass `-R <repo>`
to every `gh pr` and `gh run` command; a local remote can point at an old
repo name. `gh api` has no `-R`: its `repos/<repo>/...` path already names
the repository.

## 0. Preconditions

- The PR is open and **ready**, not a draft. Most review bots skip drafts
  and only start when a PR becomes ready. If it is a draft, mark it ready
  (`gh pr ready <n> -R <repo>`) as soon as the first real commit is pushed.
- Note the latest head: `gh pr view <n> -R <repo> --json headRefOid,isDraft,state`.
  Every gate below is about this exact commit. After every push, take the
  new head and start again from step 1.

## 1. CI gate

```bash
gh pr checks <n> -R <repo> --json name,state,bucket,link,workflow
```

`bucket` is `pass`, `fail`, `pending`, `skipping` or `cancel`. Use
`--required` when the `Drayl` section lists only required checks.

- Wait while anything relevant is `pending`; poll every 60 seconds rather
  than blocking forever.
- A path filter that skips CI (for example a docs-only change) is a pass,
  not a missing run, if the workflow's filter really excludes those files.
- Rerun only runs of the latest head. In many setups a rerun of an older
  run cancels the latest head's run.
- On failure, read the log (`gh run view <run-id> -R <repo> --log-failed`),
  fix the cause in the branch that owns the code, run the pre-push
  commands, push. Rerun a failure you believe is flaky at most once; if it
  fails again, treat it as real.
- Never force-push, never weaken or delete a check to get green.

## 2. Review gate

After every push, wait until every configured reviewer has finished **on
the latest head**, then read the findings. A review started by your fix
push can post new findings minutes after CI is green.

How to see that a review belongs to the latest head:

```bash
# check runs of review bots on the head commit
gh api repos/<repo>/commits/<sha>/check-runs --jq '.check_runs[] | {name, status, conclusion}'
# reviews and the commit each one was made on
gh api repos/<repo>/pulls/<n>/reviews --paginate --jq '.[] | {user: .user.login, state, commit_id, submitted_at}'
```

If no review for the latest head shows up within the review wait from the
`Drayl` section (default 10 minutes), do not fall back to an older review.
Report **BLOCKED: review missing on the latest head** and let the user
decide.

Many bots report their check as passed even when they found problems, so
never read the check status alone. Read all three places:

```bash
gh api repos/<repo>/pulls/<n>/comments --paginate   # inline comments
gh api repos/<repo>/pulls/<n>/reviews --paginate    # review bodies
gh api repos/<repo>/issues/<n>/comments --paginate  # top-level PR comments
```

For every finding:

- Fix it with a commit, **or** answer it with a concrete reason why it
  does not apply. No silent skips, no resolving a thread without a reply.
- Reply in the finding's own thread. Inline comments:
  `gh api repos/<repo>/pulls/<n>/comments/<comment-id>/replies -f body='Fixed in <sha>: ...'`.
  Review bodies and top-level comments: one PR comment that quotes the
  finding and answers it.
- A valid finding outside this PR's scope: open an issue and reply with
  its link. That reply answers the finding.
- After a fix push, go back to step 1 with the new head.

### No review bot: fresh independent review

When the `Drayl` section says `fresh independent review` (older sections:
`fresh subagent review`), or no reviewer is configured, get the review
from a reviewer that has **not** seen your conversation, once CI is green
on the latest head:

1. Start the reviewer, in this order of preference:
   - a new subagent with no access to your conversation, if you have one
     and your instructions allow subagents;
   - otherwise, unless your instructions rule out other agents too, a
     separate non-interactive agent run in read-only mode, for
     example `codex exec --sandbox read-only -`, `droid exec`, or
     `claude -p`, with the brief on stdin.

   Give it only: the diff (`gh pr diff <n> -R <repo>`), the PR title and
   description, `AGENTS.md`, and this brief: "Review this diff. Report only
   high-confidence bugs, security problems and broken contracts. For each:
   file:line, the problem, why it matters, a suggested fix. If there is
   nothing, say 'no findings'. Do not edit files."
2. Post its answer as a PR comment headed `Drayl review (fresh <subagent |
   agent run: tool>) on <sha>` so the review is on record.
3. Treat its findings exactly like bot findings above.

If neither works, say so in the report and mark the review as
`self-review, not independent`. That is not a passed review gate: report
BLOCKED unless the user accepts it.

### A person reviews by hand

When the `Drayl` section names a person, their review is a PR review or
a PR comment starting with `Drayl review (manual) on <sha>` for the latest
head. Ask for it in your report, wait the review wait, then report
**BLOCKED: waiting for <person>'s review on <sha>**. When you continue, read
their findings like any other. A review on an older head does not count.

## 3. Before every push

Run the commands listed under "Before every push" in the `Drayl` section.
Do not push while one of them fails.

## 4. Landing - only as the merge policy allows

- `never`: stop at done and report. The user merges.
- `after approval`: merge only after the named person approved in this
  conversation or on the PR for the current head.
- `automatic when done`: merge as soon as the done criteria hold.

Merge with a head guard so nothing lands that you did not check:
`gh pr merge <n> -R <repo> --match-head-commit <sha> [--squash|--merge|--rebase]`
(use the project's usual merge method).

Stacked PRs (a PR whose base is another PR's branch) land one at a time:

1. Merge the parent into the default branch.
2. Retarget the child: `gh pr edit <child> -R <repo> --base <default-branch>`.
3. Merge the default branch into the child branch (merge, never rebase or
   force-push) and push; CI runs again.
4. Babysit the child from step 1, then merge it.

Never merge a child into its parent branch: that lands nowhere.

After a merge, confirm the change is really on the default branch before
closing any issue. Squash and rebase merges create a new commit, so check
the PR's merge commit, not the old head:

```bash
oid=$(gh pr view <n> -R <repo> --json mergeCommit --jq .mergeCommit.oid)
git fetch origin <default-branch>
git merge-base --is-ancestor "$oid" origin/<default-branch> && echo on-default-branch
```

## Done criteria and report

Report **DONE** only when all of these hold, and name what you checked:

- CI green on the latest head (or a real path-filter skip).
- Every configured review finished on the latest head, and all three
  places were read after that.
- Every finding fixed or answered in its thread.
- Merged only if the merge policy allowed it; if merged, confirmed on the
  default branch.

Format:

```text
DONE #<n> at <short-sha>: CI <checks> green; reviews <names> finished on <short-sha>; findings <x> fixed, <y> answered; merged: <no | yes, on <branch>>
BLOCKED #<n> at <short-sha>: <reason> - <what the user must decide>
```

If a gate cannot be closed, report BLOCKED with the reason. Never report
done on an older head, an older review, or a check status alone.
