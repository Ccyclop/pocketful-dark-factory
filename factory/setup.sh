#!/usr/bin/env bash
# Prepare one clone per seat for this repository, check prerequisites, and pre-check the
# mandates with the event's own vocabulary scan.
# Run from the repository root:   TRACK=pocketful ./factory/setup.sh
# Overrides: SEATS_DIR, KICKOFF_DIR, CHECKS_DIR, VERIFIER_MODEL, ADVERSARY_MODEL
set -uo pipefail

TRACK="${TRACK:-pocketful}"
SEATS_DIR="${SEATS_DIR:-$HOME/Developer/hackathon/seats}"
KICKOFF_DIR="${KICKOFF_DIR:-$HOME/Developer/hackathon/dark-factory-wearedevs}"
CHECKS_DIR="${CHECKS_DIR:-$HOME/Developer/hackathon/band-work/checks}"
VERIFIER_MODEL="${VERIFIER_MODEL:-featherless/moonshotai/Kimi-K2.7-Code}"
ADVERSARY_MODEL="${ADVERSARY_MODEL:-featherless/zai-org/GLM-5.2}"
SEATS="planner implementer verifier adversary integrator"

ok()   { printf '  \033[32m✔\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✘\033[0m %s\n' "$1"; FAIL=1; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
FAIL=0

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "Run this inside the repository."; exit 1; }
cd "$ROOT"
ORIGIN="$(git remote get-url origin 2>/dev/null)" || { echo "No 'origin' remote. Create and push the repository first."; exit 1; }
echo "Repository: $ORIGIN   track: $TRACK"

echo "Tools"
for t in git docker claude opencode python3; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t"; else bad "$t not found on PATH"; fi
done
if docker info >/dev/null 2>&1; then ok "Docker daemon running"; else bad "Docker daemon not running"; fi
if "$KICKOFF_DIR/.venv/bin/python" -m harness --help >/dev/null 2>&1 || (cd "$KICKOFF_DIR" && .venv/bin/python -m harness --help >/dev/null 2>&1); then
  ok "event harness runs from $KICKOFF_DIR"
else
  bad "event harness not usable in $KICKOFF_DIR (create .venv and install harness/requirements.txt)"
fi
mkdir -p "$CHECKS_DIR" && ok "check output directory $CHECKS_DIR"

echo "Claude Code seats"
if python3 -c 'import json,os,sys; d=json.load(open(os.path.expanduser("~/.claude/settings.json"))); sys.exit(0 if d.get("disableClaudeAiConnectors") is True else 1)' 2>/dev/null; then
  ok "claude.ai connectors disabled at user level"
else
  warn "claude.ai connectors are not disabled in ~/.claude/settings.json; seats would inherit them"
fi

echo "OpenCode seats"
OC_CFG="$HOME/.config/opencode/opencode.json"
if python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if "featherless" in d.get("provider",{}) else 1)' "$OC_CFG" 2>/dev/null; then
  ok "global OpenCode config has the featherless provider"
else
  bad "global OpenCode config missing; run: ./factory/opencode-config.sh"
fi
if [ "$(uname)" = "Darwin" ]; then
  if [ "$(launchctl getenv OPENCODE_CONFIG 2>/dev/null)" = "$OC_CFG" ]; then ok "OPENCODE_CONFIG visible to GUI apps"
  else warn "OPENCODE_CONFIG not exported to GUI apps (resets on reboot); run ./factory/opencode-config.sh"; fi
fi

echo "Mandates"
for seat in $SEATS; do
  f="mandates/$seat.md"
  if [ ! -f "$f" ]; then bad "$f missing"; continue; fi
  if grep -qE '^Harness: .+' "$f" && grep -qE '^Model: .+' "$f"; then ok "$f names its harness and model"; else bad "$f lacks Harness:/Model: lines"; fi
done
if [ -d "$KICKOFF_DIR/harness" ]; then
  hits=$(cd "$KICKOFF_DIR" && .venv/bin/python - "$ROOT/mandates" "$TRACK" << 'PY'
import sys, pathlib
from harness import vocabulary
folder, track = pathlib.Path(sys.argv[1]), sys.argv[2]
vocab = set(vocabulary.TRACK_VOCABULARY.get(track, ()))
for p in sorted(folder.glob("*.md")):
    for n, line in enumerate(p.read_text().splitlines(), 1):
        for kind, term in vocabulary.terms_in(line):
            if term in vocab:
                print(f"{p.name}:{n} {kind} `{term}`")
PY
)
  if [ -z "$hits" ]; then ok "no $TRACK vocabulary in mandates (event scan)"; else bad "track vocabulary in mandates:"; echo "$hits" | sed 's/^/      /'; fi
fi

echo "Remote and secrets"
if git ls-remote --exit-code --heads origin main >/dev/null 2>&1; then ok "origin/main exists"; else bad "origin/main missing; push the repository first"; fi
if git ls-files -z | xargs -0 grep -nIE '(rc_[A-Za-z0-9]{16,}|fw-[A-Za-z0-9]{16,}|sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})' 2>/dev/null; then
  bad "possible credential in tracked files (see above)"
else
  ok "no obvious credentials in tracked files"
fi

echo "Seat clones in $SEATS_DIR"
if [ "$FAIL" -ne 0 ]; then
  warn "skipped until the problems above are fixed"
else
  mkdir -p "$SEATS_DIR"
  for seat in $SEATS; do
    dir="$SEATS_DIR/$seat"
    if [ -d "$dir/.git" ] && [ "$(git -C "$dir" remote get-url origin 2>/dev/null)" != "$ORIGIN" ]; then
      mkdir -p "$SEATS_DIR/.archive"
      mv "$dir" "$SEATS_DIR/.archive/$seat-$(date +%Y%m%d-%H%M%S)"
      warn "$seat: previous clone of another repository archived"
    fi
    if [ -d "$dir/.git" ]; then
      git -C "$dir" checkout -q main 2>/dev/null
      if git -C "$dir" pull --rebase --quiet origin main; then ok "$seat: updated"; else bad "$seat: pull failed"; continue; fi
    else
      if git clone --quiet "$ORIGIN" "$dir"; then ok "$seat: cloned"; else bad "$seat: clone failed"; continue; fi
    fi
    git -C "$dir" config user.name "$seat"
    git -C "$dir" config user.email "$seat@factory.local"
    case "$seat" in
      verifier|adversary)
        model="$VERIFIER_MODEL"; [ "$seat" = "adversary" ] && model="$ADVERSARY_MODEL"
        printf '{\n  "$schema": "https://opencode.ai/config.json",\n  "model": "%s"\n}\n' "$model" > "$dir/opencode.json"
        ln -sfn "mandates/$seat.md" "$dir/AGENTS.md"
        if git -C "$dir" status --porcelain -- opencode.json AGENTS.md | grep -q .; then
          bad "$seat: opencode.json or AGENTS.md is not git-ignored"
        else
          ok "$seat: model $model; mandate loaded through AGENTS.md"
        fi ;;
    esac
  done
fi

cat << TABLE

BAND Desktop agents (create once; only re-run this script to switch repositories):

  agent        runtime                              working directory          role file
  planner      Claude Code  opus[1m]  xhigh         $SEATS_DIR/planner        $SEATS_DIR/planner/mandates/planner.md
  implementer  Claude Code  opus[1m]  high          $SEATS_DIR/implementer    $SEATS_DIR/implementer/mandates/implementer.md
  integrator   Claude Code  sonnet    medium        $SEATS_DIR/integrator     $SEATS_DIR/integrator/mandates/integrator.md
  verifier     ACP: $(command -v opencode) acp       $SEATS_DIR/verifier       $SEATS_DIR/verifier/mandates/verifier.md
  adversary    ACP: $(command -v opencode) acp       $SEATS_DIR/adversary      $SEATS_DIR/adversary/mandates/adversary.md

Full settings: FACTORY.md, "Standing it up".
TABLE

if [ "$FAIL" -ne 0 ]; then echo; echo "Setup incomplete: fix the ✘ items and run again."; fi
exit "$FAIL"
