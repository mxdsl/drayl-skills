# <Check name> - <YYYY-MM-DD>

- **Result:** PASS | FAIL | INTERRUPTED (after step n/N "<label>": <reason>)
- **Build:** <commit or version on every device>
- **Devices:** <device and exact OS version with build for each, as in `os_version`; "OS changed since last run: A -> B" if the runner said so>
- **Setup:** <what was running, configuration, network, anything non-default>
- **Command:**

  ```bash
  python .agents/skills/drayl-check/scripts/drayl_check.py run --name <name> --steps <N> ... -- <command>
  ```

- **Runner state:** written to `.drayl/runs/<name>.json`, copied to `<evidence folder>/<name>.json` (input_seen: synthetic <n>, physical <n>)

## Numbers

| Step | Result | Value | Limit |
| --- | --- | --- | --- |
| 1 <label> | PASS | <value> | <limit> |

n = <number of runs or samples>. Range, median or percentiles if n > 1.

## What did not match

<Everything unexpected, even if the result is PASS. "Nothing" is allowed.>

## Limits

<What this run does not prove: one device, one run, clock offset, warm cache, ...>

## Follow-up

- Issues: <links for every FAIL or finding>
- Raw evidence: `<evidence folder>` (README inside)
