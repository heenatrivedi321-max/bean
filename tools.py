"""Real tool implementations for the agent loop.

Read-only tools execute immediately, no gate. `run_shell` and editing a
pre-existing file always require explicit y/N confirmation — no exceptions,
same principle as the Zerodha bot's trade-confirmation gate: an unreliable
local model never gets unattended access to a destructive action.
"""
import fnmatch
import subprocess
from pathlib import Path

MAX_READ_CHARS = 4000  # keep tool results small enough to fit back in a prompt

# Confirmed necessary the hard way: the agent once mistook a truncated
# read_file result for real content and asked to overwrite cli.py with it,
# and the user approved it because the preview didn't make the danger
# obvious. This is a hard block, not a confirmation prompt — no amount of
# "yes" should let the tool destroy its own source.
PROTECTED_FILES = {
    "cli.py", "agent_loop.py", "tools.py", "local_worker.py", "verify.py",
    "config.py", "setup_wizard.py", "memory.py", "notify.py",
    "background_runner.py", "cloud_orchestrator.py",
}


def _is_protected(path: str) -> bool:
    return Path(path).name in PROTECTED_FILES


def list_files(pattern: str = "*") -> str:
    cwd = Path.cwd()
    matches = sorted(str(p.relative_to(cwd)) for p in cwd.rglob("*")
                      if p.is_file() and fnmatch.fnmatch(p.name, pattern)
                      and ".git" not in p.parts)
    if not matches:
        return f"No files matching '{pattern}' in {cwd}"
    return "\n".join(matches[:200])


def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"ERROR: {path} does not exist"
    if not p.is_file():
        return f"ERROR: {path} is not a file"
    try:
        text = p.read_text()
    except Exception as e:
        return f"ERROR reading {path}: {e}"
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + f"\n... (truncated, {len(text)} chars total)"
    return text


def search_files(query: str) -> str:
    cwd = Path.cwd()
    hits = []
    for p in cwd.rglob("*.py"):
        if ".git" in p.parts:
            continue
        try:
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if query.lower() in line.lower():
                    hits.append(f"{p.relative_to(cwd)}:{i}: {line.strip()}")
        except Exception:
            continue
        if len(hits) >= 50:
            break
    return "\n".join(hits) if hits else f"No matches for '{query}'"


def confirm(prompt_text: str) -> bool:
    answer = input(f"{prompt_text} [y/N]: ").strip().lower()
    return answer == "y"


def run_shell(command: str) -> str:
    print(f"\n[agent wants to run]: {command}")
    if not confirm("Allow this command to run?"):
        return "DECLINED: the user did not approve running this command."
    try:
        result = subprocess.run(command, shell=True, capture_output=True,
                                 text=True, timeout=30)
        output = (result.stdout + result.stderr).strip()
        return output[:MAX_READ_CHARS] if output else "(command produced no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 30s"
    except Exception as e:
        return f"ERROR: {e}"


def edit_file(path: str, content: str, created_this_session: set) -> str:
    if _is_protected(path):
        return (f"BLOCKED: {path} is part of localcoder's own source code and can never "
                f"be edited by the agent, no confirmation can override this.")

    # A truncated read_file result ("... (truncated, N chars total)") is
    # never valid content to write back — confirmed this exact confusion
    # caused real damage. Reject it outright instead of trusting a preview.
    if "(truncated," in content and len(content) < 200:
        return ("BLOCKED: this looks like a truncated tool-result marker, not real file "
                "content — refusing to write it. Read the file in smaller pieces if you "
                "need the full content.")

    p = Path(path)
    if p.exists() and path not in created_this_session:
        print(f"\n[agent wants to overwrite existing file]: {path}")
        print("--- new content preview (first 500 chars) ---")
        print(content[:500])
        print("--- end preview ---")
        if not confirm(f"Allow overwriting {path}?"):
            return f"DECLINED: the user did not approve editing {path}."
    p.write_text(content)
    created_this_session.add(path)
    return f"Wrote {path} ({len(content)} chars)"


TOOL_FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "search_files": search_files,
    "run_shell": run_shell,
    # edit_file handled specially in agent_loop.py — needs the created_this_session set
}
