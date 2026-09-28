#!/usr/bin/env bash
# Writes the global OpenCode config (Featherless provider, unattended permission
# guardrails) to ~/.config/opencode/opencode.json, outside every repository, and on macOS
# exposes its path to GUI-launched apps such as BAND Desktop.
# Requires FEATHERLESS_API_KEY in the environment; the key never enters a repository.
# OPENCODE_EXTRA_ALLOW: colon-separated directories seats may reach outside their clone.
set -euo pipefail
export OPENCODE_EXTRA_ALLOW="${OPENCODE_EXTRA_ALLOW:-$HOME/Developer/hackathon/dark-factory-wearedevs:$HOME/Developer/hackathon/band-work/checks}"

python3 - << 'PYEOF'
import json, os, sys
key = os.environ.get("FEATHERLESS_API_KEY", "")
if not key:
    sys.exit("FEATHERLESS_API_KEY is not set in this shell.")
external = {"*": "deny", "/tmp/**": "allow", "/private/tmp/**": "allow",
            "/var/folders/**": "allow", "/private/var/folders/**": "allow"}
for d in filter(None, os.environ["OPENCODE_EXTRA_ALLOW"].split(":")):
    external[d.rstrip("/") + "/**"] = "allow"
cfg = {
  "$schema": "https://opencode.ai/config.json",
  "provider": {"featherless": {
    "npm": "@ai-sdk/openai-compatible",
    "name": "Featherless",
    "options": {"baseURL": "https://api.featherless.ai/v1", "apiKey": key},
    "models": {
      "zai-org/GLM-5.2": {"name": "GLM 5.2"},
      "moonshotai/Kimi-K2.7-Code": {"name": "Kimi K2.7 Code"},
      "deepseek-ai/DeepSeek-V4-Flash": {"name": "DeepSeek V4 Flash"}}}},
  "permission": {
    "edit": "allow",
    "bash": {"*": "allow", "sudo *": "deny",
             "git push --force*": "deny", "git push -f*": "deny",
             "git push * --force*": "deny", "git push * -f*": "deny"},
    "external_directory": external,
    "doom_loop": "deny"}
}
p = os.path.expanduser("~/.config/opencode/opencode.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, "w") as f:
    json.dump(cfg, f, indent=2)
os.chmod(p, 0o600)
print("wrote " + p)
PYEOF

if [ "$(uname)" = "Darwin" ]; then
  launchctl setenv OPENCODE_CONFIG "$HOME/.config/opencode/opencode.json"
  echo "OPENCODE_CONFIG exported to GUI apps (lasts until reboot)."
  echo "Quit BAND Desktop completely, run: pkill -x jamd   then reopen BAND."
fi
