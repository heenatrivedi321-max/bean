#!/usr/bin/env bash
# bean — one command, everything happens.
#
# Usage:
#   ./install.sh              # from a clone
#   curl -fsSL <url> | bash   # hosted copy
#
# Checks and installs, in order:
#   1. Python 3.12 + bean's deps (rich, requests) — via uv, automatically
#   2. Ollama (the local model runtime) — automatically
#   3. Starts Ollama (the desktop app if present, else a plain daemon),
#      then launches bean
#
#   --dry-run   print what would be installed without touching anything
#   --no-run    install everything but don't launch bean
set -euo pipefail

DRY_RUN=0
NO_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-run) NO_RUN=1 ;;
  esac
done

say()  { printf '\033[1;33mbean\033[0m \033[90m›\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32mbean\033[0m \033[90m›\033[0m %s\n' "$1"; }
warn() { printf '\033[1;31mbean\033[0m \033[90m›\033[0m %s\n' "$1"; }

if [ "$DRY_RUN" = "1" ]; then
  say "dry run — nothing will be installed or changed"
  run() { printf '  would run: %s\n' "$*"; }
else
  run() { "$@"; }
fi

# ------------------------------------------------------------------ sources

# Two ways to run: from a clone (./install.sh) or piped from the internet
# (curl | bash). Piped runs have no script file, so $BASH_SOURCE/$0 are
# unusable — clone into a stable home instead of wherever the user happens
# to be.
if [ -f "$(dirname "$0" 2>/dev/null)/bean.py" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
else
  SCRIPT_DIR="$HOME/.bean"
fi
BEAN_FILE="$SCRIPT_DIR/bean.py"
BEAN_REPO="${BEAN_REPO:-https://github.com/heenatrivedi321-max/bean.git}"

if [ ! -f "$BEAN_FILE" ]; then
  say "bean isn't here yet — grabbing it from $BEAN_REPO"
  if [ "$DRY_RUN" = "0" ]; then
    mkdir -p "$HOME"
    if [ -d "$SCRIPT_DIR" ] && [ ! -f "$BEAN_FILE" ]; then
      rm -rf "$SCRIPT_DIR"
    fi
    git clone --depth 1 "$BEAN_REPO" "$SCRIPT_DIR"
  else
    printf '  would run: git clone --depth 1 %s %s\n' "$BEAN_REPO" "$SCRIPT_DIR"
  fi
  BEAN_FILE="$SCRIPT_DIR/bean.py"
fi

# -------------------------------------------------------- python + deps
#
# Preferred path: uv run — one command that fetches Python 3.12, installs
# rich + requests, and runs bean. No system installs, no PATH juggling.
# Fallback: a system python3 with pip, deps installed --user.

have_python() {
  command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

PY=""
if command -v uv >/dev/null 2>&1; then
  PY="uv run --quiet --python 3.12 --with rich --with requests python"
elif have_python && command -v pip3 >/dev/null 2>&1; then
  if ! python3 -c 'import rich, requests' >/dev/null 2>&1; then
    say "installing bean's deps with pip"
    run pip3 install --user --quiet rich requests
  fi
  PY="python3"
else
  say "no Python or uv found — installing uv (it brings its own Python)"
  if [ "$DRY_RUN" = "0" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  else
    printf '  would run: curl -LsSf https://astral.sh/uv/install.sh | sh\n'
  fi
  PY="uv run --quiet --python 3.12 --with rich --with requests python"
fi

# ------------------------------------------------------------------ ollama

if ! command -v ollama >/dev/null 2>&1; then
  say "installing Ollama — the engine that runs your local models"
  if [ "$DRY_RUN" = "0" ]; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    printf '  would run: curl -fsSL https://ollama.com/install.sh | sh\n'
  fi
fi

# ------------------------------------------------------- the 'bean' command

# Make `bean` work from any directory, not just this repo. Wrapper script so
# it uses the same Python+deps resolution chosen above.
if [ "$DRY_RUN" = "0" ]; then
  mkdir -p "$HOME/.local/bin"
  BIN="$HOME/.local/bin/bean"
  printf '#!/usr/bin/env bash\nexec %s %s "$@"\n' "$PY" "$BEAN_FILE" > "$BIN"
  chmod +x "$BIN"
  ok "installed the 'bean' command ($BIN)"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) say "add ~/.local/bin to your PATH to run 'bean' from anywhere:" ;;
  esac
fi

# ------------------------------------------------------------------ start

# macOS with the desktop app installed: let the app own the server on 11434.
# It boots its own daemon and gives the user the chat UI bean hands off to.
# CLI-only machines (Linux, or macOS without the app) get a plain daemon.
OLLAMA_APP="/Applications/Ollama.app"
if [ "$DRY_RUN" = "0" ]; then
  if [ -d "$OLLAMA_APP" ]; then
    if ! curl -s -o /dev/null --max-time 3 http://localhost:11434/api/tags 2>/dev/null; then
      say "opening the Ollama app (it runs the local engine)"
      open -a Ollama
      for i in 1 2 3 4 5 6 7 8 9 10; do
        sleep 1
        curl -s -o /dev/null --max-time 2 http://localhost:11434/api/tags 2>/dev/null && break
      done
    fi
  else
    if ! curl -s -o /dev/null --max-time 3 http://localhost:11434/api/tags 2>/dev/null; then
      say "starting Ollama"
      nohup ollama serve >/dev/null 2>&1 &
      sleep 3
    fi
  fi
fi

# Never leave a second Ollama daemon behind: if the machine already runs one
# (e.g. the Ollama app), the copy we spawned must go. One daemon owns 11434.
if [ "$DRY_RUN" = "0" ]; then
  DAEMONS="$(lsof -iTCP:11434 -sTCP:LISTEN -P 2>/dev/null | grep -c ollama || true)"
  if [ "$DAEMONS" -gt 1 ]; then
    say "found a second Ollama daemon — removing it"
    brew services stop ollama >/dev/null 2>&1 || true
    pkill -f "/opt/homebrew/opt/ollama/bin/ollama serve" >/dev/null 2>&1 || true
    pkill -f "/usr/local/bin/ollama serve" >/dev/null 2>&1 || true
    pkill -f "^ollama serve" >/dev/null 2>&1 || true
    sleep 2
  fi
fi

ok "everything's in place"
if [ "$NO_RUN" = "0" ] && [ "$DRY_RUN" = "0" ]; then
  ok "opening bean"
  cd "$SCRIPT_DIR"
  exec $PY "$BEAN_FILE"
fi