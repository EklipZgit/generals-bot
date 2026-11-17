# Agent Rules

## Fundamental decision logging (viewInfo)

Any time you add or change code that alters a **fundamental decision** the bot
makes — committing to or aborting an attack/plan, vetoing or overriding a move
another system already evaluated, switching modes/phases, or releasing a
committed plan — the verdict and its reason **must** be emitted via
`bot.viewInfo.add_info_line` (or `bot.info` for banner-level decisions), not
only `logbook.info`.

This matters **most** when another system already logged the opposite verdict
earlier in the same turn: e.g. a QK "kill race chance 1.000" line followed by
silence when a different system vetoes the attack makes the turn log read as
incoherent. The veto/override itself must appear in viewInfo so the log shows
*why* the advertised move did not happen.

Notes:

- `viewInfo.add_info_line` already calls `logbook.info`, so the text log loses
  nothing — prefer it over bare `logbook.info` for any decision line.
- Keep `logbook.info` for verbose math/geometry diagnostics, and keep
  per-candidate spam guards (eligible-only) intact.
- This mirrors the `--- Fundamental decision logging (viewInfo) ---` section
  in `.windsurfrules`.

## Reporting added log lines

When you finish work that added viewInfo decision lines, the final message to
the user must call out each new line in bold, in the form:

> **"I added 'sample log line' to view info output to show when X occurs"**

Quote the actual emitted string, so the user can decide whether to keep it,
tweak the wording, or decide the logging isn't worth having.
