"""Calls the local coding specialist via Ollama's clean HTTP API.

Reuses the exact pattern proven all night: system + prompt + stream:false +
explicit num_predict, never the CLI (its spinner output corrupted results
earlier in testing).
"""
import json
import subprocess
import urllib.request

import config
import ui

STRICT_CODE_SYSTEM = (
    "Output ONLY the complete code. No explanation, no markdown fences, "
    "no extra text before or after the code. "
    "CRITICAL: always include actual example calls that exercise the code's "
    "real behavior (e.g. under an `if __name__ == '__main__':` block with "
    "print statements showing real inputs and outputs, including edge cases "
    "mentioned in the request). Defining a function with no calls proves "
    "nothing when the code is run — the examples must actually execute the "
    "logic, not just define it."
)


def stream(prompt: str, system: str, model: str = None, num_predict: int = 2000,
           timeout: int = 200, on_token=None) -> str:
    """Streams tokens as they're produced so the caller can show live progress.

    Added because the minimal UI left you staring at a static spinner for a
    minute with no way to tell whether anything was actually happening.
    """
    model = model or config.CODING_SPECIALIST
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": num_predict, "num_ctx": config.DEFAULT_NUM_CTX},
    }
    req = urllib.request.Request(
        config.OLLAMA_API,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    parts = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            if not raw.strip():
                continue
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                continue
            piece = chunk.get("response", "")
            if piece:
                parts.append(piece)
                if on_token:
                    on_token(piece)
            if chunk.get("done"):
                break
    return "".join(parts)


def _call(prompt: str, system: str, model: str = None, num_predict: int = 2000, timeout: int = 200) -> str:
    model = model or config.CODING_SPECIALIST
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": num_predict, "num_ctx": config.DEFAULT_NUM_CTX},
    }
    req = urllib.request.Request(
        config.OLLAMA_API,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        result = json.load(r)
    return result.get("response", "")


def generate(prompt: str, model: str = None, num_predict: int = 2000, timeout: int = 200,
             silent: bool = False) -> str:
    if silent:  # rich's console.status() fights Textual for terminal control — TUI mode
        return strip_fences(_call(prompt, STRICT_CODE_SYSTEM, model, num_predict, timeout))
    with ui.spinner(f"generating with {model or config.CODING_SPECIALIST}..."):
        return strip_fences(_call(prompt, STRICT_CODE_SYSTEM, model, num_predict, timeout))


STRICT_HTML_SYSTEM = (
    "Output ONLY a complete, self-contained HTML document starting with "
    "<!DOCTYPE html>. All CSS must be inline in a <style> tag and all JS in a "
    "<script> tag — no external files, no CDN links, no build step. "
    "Include every element the request asks for. No explanation, no markdown "
    "fences, no text before or after the document."
)


PLAN_SYSTEM = (
    "State your approach to this coding task in 2-4 plain sentences. "
    "No code, no markdown fences, just your actual reasoning about how "
    "you'll solve it and what (if anything) you need to check first."
)


def plan(task: str, model: str = None, silent: bool = False) -> str:
    """The real 'shows its thinking' step — genuine model output, not a
    spinner animation. Displayed live by the caller before any action.
    The spinner here covers real wait time; the panel shown afterward is
    the model's actual returned text, not decoration."""
    if silent:
        return _call(task, PLAN_SYSTEM, model, num_predict=200, timeout=120).strip()
    with ui.spinner("thinking..."):
        return _call(task, PLAN_SYSTEM, model, num_predict=200, timeout=120).strip()


TOOL_SYSTEM = (
    "You are solving a coding task and may use tools to gather context or "
    "take action before writing final code. Available tools:\n"
    "- list_files(pattern) — list files matching a glob pattern in the working directory\n"
    "- read_file(path) — read an existing file's contents\n"
    "- search_files(query) — search .py files for a text query\n"
    "- run_shell(command) — run a shell command (requires user approval)\n"
    "- edit_file(path, content) — write or overwrite a file (requires approval if it already exists)\n\n"
    "Respond with EXACTLY ONE of:\n"
    '1. A tool call as raw JSON on one line: {"tool": "read_file", "args": {"path": "foo.py"}}\n'
    '2. Final code, prefixed with the exact line "FINAL_CODE:" then the complete code, nothing else after.\n'
    "No explanation outside of those two formats."
)


def next_step(task: str, plan_text: str, history: str, model: str = None) -> str:
    prompt = f"Task: {task}\n\nYour plan: {plan_text}\n\nTool results so far:\n{history}\n\nWhat's your next step?"
    with ui.spinner("deciding next step..."):
        return _call(prompt, TOOL_SYSTEM, model, num_predict=800, timeout=150).strip()


def unload(model: str = None):
    """Explicitly frees the model's RAM after use. Tonight proved Ollama
    doesn't reliably do this on its own — lingering llama-server processes
    ate 10GB+ of RAM more than once during testing, and `ollama stop`
    reports success without actually killing the process on this setup
    (confirmed directly during testing). Direct process kill is what
    actually worked earlier tonight, so that's what's used here."""
    model = model or config.CODING_SPECIALIST
    try:
        subprocess.run(["ollama", "stop", model], capture_output=True, timeout=10)
    except Exception:
        pass
    try:
        subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, timeout=10)
    except Exception:
        pass


def strip_fences(text: str) -> str:
    """Handles both the clean case (fences as first/last line) AND the case
    found during real testing where a weaker model, under retry pressure,
    wrapped the code in explanatory prose with the fence buried mid-response
    — the old symmetric-only stripping left that as broken hybrid content."""
    import re
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```") and lines[-1].strip().startswith("```"):
        return "\n".join(lines[1:-1])

    # Fallback: find a fenced block anywhere in the text and extract it.
    match = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    return text  # no fences found at all — already clean
