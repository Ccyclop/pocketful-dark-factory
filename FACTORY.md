# The Factory

A five-seat software factory that runs in BAND Desktop across three model families. Given a written task, it copies the specification verbatim into a contract, builds against it one small work item at a time, verifies every item independently, attacks each finished milestone, and releases only what builds and passes from a fresh clone under the judged conditions. The task dispatch is the only human input: seats decide among themselves, log their decisions, and report at the end.

`FACTORY.md` and `mandates/` are enough to stand it up; `factory/` holds the scripts and the dispatch briefs.

## Seats

| Seat | Harness | Model | Reasoning | Owns |
|---|---|---|---|---|
| planner | Claude Code | claude-opus-5-5[1m] | xhigh | contract, decisions, plan, gates, final report |
| implementer | Claude Code | claude-opus-5-5[1m] | high | production code |
| verifier | OpenCode, run as an ACP agent | moonshotai/Kimi-K2.7-Code (Featherless) | provider default | acceptance tests and verdicts |
| adversary | OpenCode, run as an ACP agent | zai-org/GLM-5.2 (Featherless) | provider default | attacks on accepted work |
| integrator | Claude Code | claude-sonnet-5 | medium | clean builds, releases, metrics |

Every seat works in its own clone of the repository under its own git identity (`git log` authors are seat names, and every commit ends with a `Seat:` trailer), and all seats sync through `origin/main`.

## How work flows

```
task ─► planner: CONTRACT.md + DECISIONS.md
          │
          └─► WORK-ITEM ──► implementer ──► EVIDENCE ──► verifier ──► ACCEPT ─┐
                   │             ▲                          │                 │
                   └────────────►│ (verifier writes tests   └──► REJECT ──────┘
                                 │  from the requirements        back to implementer
                                 │  while code is written)
all items ACCEPT ─► MILESTONE-CANDIDATE ─► adversary ─► BREAK ─► fix item (break case = criterion)
                                                   └─► NO-BREAK ─► MILESTONE-COMPLETE ─► integrator
integrator: fresh clone, strictest check mode ─► RELEASE PASS (tag, frozen folder, METRICS.md) ─► next milestone
all milestones released or blocked ─► FINAL REPORT to the human
```

| Message | From → to | Carries |
|---|---|---|
| WORK-ITEM | planner → implementer, verifier | verbatim requirements and contract entries, acceptance criteria, folder, checks |
| EVIDENCE | implementer → verifier, planner | full revision, criteria copied verbatim, build/run commands, check results |
| ACCEPT / REJECT | verifier → implementer, planner | revision tested, tests and checks run, review findings, reproducible failing cases |
| MILESTONE-CANDIDATE | planner → adversary | milestone requirements and contract, revision, build/run |
| BREAK / NO-BREAK | adversary → planner (and implementer) | violated contract id, reproduce command, frequency; or attacks run by category |
| MILESTONE-COMPLETE | planner → integrator | revision, folder, checks, delivery rules |
| RELEASE PASS / FAIL | integrator → planner | build result, check output, metrics |
| FINAL REPORT | planner → human | outcome per milestone, revisions, metrics, blockers |

Seats receive only messages addressed to them, so every handoff is self-contained: requirements are pasted, never pointed to.

## Gates

1. No item is done without an ACCEPT on a named, pushed revision.
2. No milestone is complete without a NO-BREAK on its final revision.
3. No milestone is released without a fresh-clone build and a full run of this and every earlier milestone's checks in the strictest mode the task provides.
4. A released delivery folder is never modified again.

The room's work board mirrors the gates: an item is marked completed only by the gate that closes it.

## Design decisions and what they cost

**Independent verification.** The verifier and adversary run on model families different from the implementer's and from each other's, in their own clones, and write their tests from the requirements before reading code. Author and checker then share neither blind spots, workspace nor reasoning. Cost: a second and third model provider, and a verifier that is slower than a same-model reviewer.

**Contract first.** Before a milestone's first item the planner copies every externally visible name, shape, error condition and invariant into `CONTRACT.md`, verbatim, and logs every interpretation in `DECISIONS.md`. The checks shipped with a task are only a sample; the contract is how the factory builds what the checks never ask. Cost: one long planning turn per milestone before any code exists.

**Every break becomes a permanent test.** The adversary attacks accepted work for concurrency, replay, malformed input and state violations. A BREAK becomes a fix item whose criterion is the break case, which the verifier adds to the acceptance suite, so the suite only grows and later milestones cannot regress. Cost: one attack campaign per milestone.

**Release from a fresh clone.** The integrator never builds from a working checkout, so nothing cached on the machine can make a folder pass that would fail for a judge.

**The factory measures itself.** Each release appends items, REJECTs, first-pass acceptance rate, BREAKs, fix cycles and wall time to `METRICS.md`; spend is logged in `factory/COST.md`.

**Spend where the volume is.** The seat that runs most often (the verifier, once per item) sits on the cheapest capable model, and the seat that runs least (the adversary, once per milestone) on the more expensive one.

**Guardrails in the runtime, not only in the prompt.** Force-push and `sudo` are denied by the OpenCode permission config; paths outside a seat's clone are denied except temp, the event kit and the check output directory; Claude seats run with no inherited connectors, hooks or skills.

## How the factory catches and recovers from bad work

- **Wrong code:** the verifier rejects with a reproducible failing case; the implementer reproduces it first, fixes the cause and resends EVIDENCE.
- **An item that keeps failing:** after three REJECTs the planner rewrites or splits it and records why.
- **Work that passes review but not reality:** the adversary's BREAK turns the failure into a fix item and a permanent acceptance test.
- **Code that only works on this machine:** the integrator's fresh-clone release in the strictest check mode fails it and names the likely item.
- **Code shaped to the checks:** the verifier rejects special-casing even when the check passes.
- **An interrupted run:** seats resume from the repository, not from memory: each pulls, inspects what was pushed, and redoes any step that did not land.
- **Something that cannot be done:** the planner records the blocker and its evidence, continues with independent work, and reports it; nobody asks the human.

## What we tried that failed

- **BAND's native OpenCode runtime** intermittently could not offer a custom OpenAI-compatible provider at startup: its model check raced the provider load, so seats failed to start about half the time. The OpenCode seats now run as ACP agents (`opencode acp`).
- **Mandates for ACP seats:** BAND passes an ACP agent only its description, truncated, not the role file. We found this by asking every seat, without file access, for a detail only its mandate contains: the Claude Code seats answered, the ACP seats could not. Each OpenCode seat now loads its mandate from a git-ignored `AGENTS.md` linked to `mandates/<seat>.md`. OpenCode's `instructions` setting did not load it.
- **Claude Code "Minimal — credentials only"** runs in bare mode, which reads only API keys, so a subscription login fails. The seats use the operator's Claude setup with claude.ai connectors disabled at user level, because BAND's runtime probe starts outside the repository where a project setting does not apply, and BAND rejects `--strict-mcp-config` as an argument it owns.
- **Permission prompts:** an unattended OpenCode session auto-rejects every "ask", and BAND's "approve all" would approve every one. Permissions are therefore explicit allow and deny rules, with deny as the default outside the seat's clone.
- **The board:** in our first run the implementer marked its item done at handoff, before review. The board rule now ties completion to the gate that closes each item.
- **Asking the human:** our first planner mandate allowed one question with a default. A dark-factory run allows none, so decisions are now made and logged inside the band.
- **Machine sleep** froze a run mid-request; the band recovered from the repository, but the fix is simply to keep the machine awake for a run.

## Standing it up

Prerequisites: macOS or Linux, Docker, git and `gh`, Python 3.12+, BAND Desktop, Claude Code with a subscription, OpenCode (`@opencode/cli` or `opencode-ai`), a Featherless key in `FEATHERLESS_API_KEY`, and the event kit with its harness installed.

1. **Claude Code without connectors** (user level, for the duration of the run; restore from the `.bak` afterwards):
   `cp ~/.claude/settings.json ~/.claude/settings.json.bak`, then set `"disableClaudeAiConnectors": true` in `~/.claude/settings.json`.
2. **OpenCode provider and guardrails, outside any repository:** `./factory/opencode-config.sh`, then quit BAND Desktop, run `pkill -x jamd` and reopen it. Repeat after a reboot.
3. **Seat clones:** `TRACK=<track> ./factory/setup.sh` from the repository root. It checks the tools, pre-checks the mandates with the event's own vocabulary scan, and creates or re-points one clone per seat under `~/Developer/hackathon/seats/<seat>` with that seat's git identity; the OpenCode seats also get their model (`opencode.json`) and mandate (`AGENTS.md`), both git-ignored.
4. **Five agents in BAND Desktop** (Agents → Create your own; no tags). Role file: `<seat clone>/mandates/<seat>.md`.

   | Field | planner | implementer | integrator |
   |---|---|---|---|
   | Runtime | Claude Code | Claude Code | Claude Code |
   | Working directory | seat clone | seat clone | seat clone |
   | Model | `opus[1m]` | `opus[1m]` | `sonnet` |
   | Reasoning effort | xhigh | high | medium |
   | Permission mode | Auto | Auto | Auto |
   | Claude customizations | Use my Claude setup | same | same |
   | Environment allowlist | `PATH,HOME,SSH_AUTH_SOCK` | same | same |

   | Field | verifier | adversary |
   |---|---|---|
   | Runtime | ACP agent, custom command | ACP agent, custom command |
   | Command / arguments | absolute path of `opencode` / `acp` | same |
   | Working directory | seat clone | seat clone |
   | Approval policy | Allow automatically | Allow automatically |
   | Environment allowlist | `PATH,HOME,SSH_AUTH_SOCK,OPENCODE_CONFIG` | same |

   In each Claude seat's runtime check, expect one MCP server (`jam`) and the intended model.
5. **Check every seat** with a message it can only answer from its mandate, without reading files, such as the first line of its report format.
6. **Run:** one room with the five agents; paste a dispatch brief from `factory/briefs/` addressed to @planner (one per stage, or all stages in one), keep the machine awake, and send nothing between dispatches.

Switching to another task means writing a new brief and re-running `setup.sh` against the new repository. The mandates do not change.

## Measured cost and time

Recorded per milestone in `factory/COST.md` and `METRICS.md`; summary to be completed after the submitted run.

## Limitations

1. **Filesystem boundaries between seats are advisory.** OpenCode's directory rule blocks file tools but not shell commands: during setup, an OpenCode seat listed a sibling clone with `ls`. Independence rests on separate model families, separate clones and the mandates. One Docker sandbox per seat would enforce it, but BAND does not sandbox OpenCode seats.
2. **Claude seats share the operator's subscription limits**, so a long run can be throttled; the heaviest seat (implementer) is the one to move to a smaller model first.
3. To be completed after the submitted run.
