# Cost and time log

Filled at every release. Sources: BAND Desktop Analytics; the Featherless Subscription page (itemised per request); `/cost` or `/usage` in the Claude Code seats; `METRICS.md` for REJECTs, BREAKs and wall time.

## Models

| Seat | Harness | Model | Billing |
|---|---|---|---|
| planner | Claude Code | claude-opus-5-5[1m] | Claude Max subscription |
| implementer | Claude Code | claude-opus-5-5[1m] | Claude Max subscription |
| integrator | Claude Code | claude-sonnet-5 | Claude Max subscription |
| verifier | OpenCode (ACP) | moonshotai/Kimi-K2.7-Code | Featherless per-request credits |
| adversary | OpenCode (ACP) | zai-org/GLM-5.2 | Featherless per-request credits |

Measured during setup: Kimi K2.7 Code about $0.83 per million input tokens, with cached input roughly four times cheaper; GLM-5.2 about $1.45 per million. Every OpenCode request carries a baseline of 7 to 8 thousand input tokens.

## Per milestone

| Run | Milestone | Wall time | Featherless $ | Claude usage | Items | REJECTs | BREAKs | Human messages |
|---|---|---|---|---|---|---|---|---|
