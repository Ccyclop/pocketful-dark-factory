# METRICS

## M1 — pocketful stage 1, "payments and settlements"

- Work items: 10 (WI-1.1 … WI-1.10)
- Items accepted: 10
- REJECTs: 0
- First-pass acceptance rate: 100% (10/10 accepted with no REJECT)
- Attack campaigns: 1
- BREAKs found: 0
- Fix items: 0
- Fix cycles: 0
- Decisions logged: D1–D26 (DECISIONS.md)
- Wall time: contract commit 6881d7b (2026-09-28T14:11:37+04:00) → NO-BREAK commit 8a790f4 (2026-09-28T18:41:41+04:00) ≈ 4h 30m, plus release time
- Messages to the human other than the final report: 0
- Official stage-1 checks at the accepted code: 147/147 (implementer/verifier host runs)
- Release checks (fresh clone at 8a790f40947d5851ef414b1c6dcdad8cfbc0ae3a):
  - Build: `docker build -t pocketful-stage-1 stage-1` — pass, 2.1s
  - Health: `GET /health` — 200 `{"status":"ok"}` within 1s of start
  - Isolated harness (`harness run --track pocketful --stage 1 --mode isolated`): stage 1 pass, stage 2 fail (expected), claimed stage: 1
  - Acceptance suite (`pytest acceptance -q`): 203 passed in 622.76s
- Release tag: `M1` at `8a790f40947d5851ef414b1c6dcdad8cfbc0ae3a`
