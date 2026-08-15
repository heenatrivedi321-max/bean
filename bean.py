#!/usr/bin/env python3
"""bean — describe what you need, get the right local model, done.

Flow:
  1. you describe what you need a helper for
  2. a cloud model reads it and picks the right local model for your hardware
  3. it downloads, with a real progress bar
  4. the cloud model steps out — the Ollama app opens with your model
     already loaded. From then on everything runs on your machine.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# bean's UI uses ✓ ✗ ● ▪ — glyphs the Windows console can't encode with its
# default codepage (cp1252), which crashed with UnicodeEncodeError. Force
# UTF-8 so the same UI works everywhere.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.text import Text

import catalog
import config
import onboard
import setup_wizard
import requests

console = Console()

VERSION = "0.2.0"
ACCENT = "#d97757"
DIM = "grey54"
GREEN = "green"

# ---------------------------------------------------------------- ui helpers

def banner():
    console.print()
    console.print(Text("bean", style=f"bold {ACCENT}"))
    console.print(Text("find the right local model · free · local · private", style=DIM))
    console.print()


def ask(question: str) -> str:
    """One clean input prompt — no echo tricks, no escape codes."""
    try:
        answer = console.input(f"  {question}  ")
    except (EOFError, KeyboardInterrupt):
        return ""
    return answer.strip()


def status(msg: str):
    console.print(f"  [{DIM}]{msg}[/{DIM}]")


def success(msg: str):
    console.print(f"  [{GREEN}]✓[/{GREEN}] {msg}")


def error(msg: str):
    console.print(f"  [red]✗[/red] {msg}")


def meta(label: str, detail: str, secs: float | None = None):
    tail = f" · [{DIM}]{secs:.1f}s[/{DIM}]" if secs is not None else ""
    console.print(f"  [{ACCENT}]▪[/{ACCENT}] [{DIM}]{label}[/{DIM}]"
                   f" · [{DIM}]{detail}[/{DIM}]{tail}")
    console.print()


# ---------------------------------------------------------------- cloud pick

RECOMMEND_SYSTEM = """You are bean's helper, chatting with a user who is about
to set up a local AI model on their own machine. You know how much RAM is
free and you have a catalog of available local models.

- If the user is just greeting you or chatting, respond as a friendly, brief
  helper. Ask what they'd like a model to do for them (coding, writing,
  thinking, vision, or just chatting). Plain text only — no JSON.
- Once the user states an actual need, reply with strict JSON, nothing else:
{
  "reply": "one or two friendly sentences explaining the choice, plainly",
  "models": [
    {"name": "<exact name from catalog>", "why": "<short, honest reason>"}
  ]
}

Picking rules (only when a need is stated):
1. Figure out what the user actually needs: coding, writing, reasoning/math,
   vision, or general chat.
2. Find catalog models whose USES match that need AND whose SIZE fits the
   RAM budget.
3. Pick the SMALLEST matching model that fits — downloads are the slowest
   part of setup. If several different jobs are wanted, list up to 2.
4. If NO model matches within the budget, say so honestly and pick the
   smallest general model that fits as a fallback.

Rules: never invent a model name. Never exceed the RAM budget."""


def _parse_recommendation(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    parsed = json.loads(text[start:end + 1])
    valid = {m["name"] for m in catalog.CATALOG}
    parsed["models"] = [m for m in parsed.get("models", []) if m.get("name") in valid]
    return parsed if parsed["models"] else None


def _catalog_lines(budget_gb: float) -> list[str]:
    return [
        f'{m["name"]} ({m["gb"]}GB, {", ".join(m["uses"])}, {m["note"]})'
        for m in catalog.CATALOG if m["gb"] <= budget_gb]


def recommend_via_proxy(conversation: list[dict], budget_gb: float) -> str | None:
    """Ask our Worker, which holds the key. No key ships with bean.

    Returns the raw model reply: plain chat text, or the recommendation JSON
    once the user has stated a need. The caller decides which it is.
    """
    if not config.PROXY_URL:
        return None
    options = _catalog_lines(budget_gb)
    if not options:
        return None

    r = requests.post(config.PROXY_URL, timeout=60,
                      json={"messages": conversation, "catalog": "\n".join(options),
                            "budget_gb": budget_gb})
    if r.status_code != 200:
        raise RuntimeError(r.json().get("error", f"proxy {r.status_code}"))
    return r.json()["content"]


def recommend(conversation: list[dict], budget_gb: float) -> str | None:
    """Direct provider call — for power users with their own key."""
    key_info = config.cloud_api_key()
    if not key_info:
        return None
    _, key = key_info

    options = _catalog_lines(budget_gb)
    if not options:
        return None

    need = conversation[-1]["content"] if conversation else ""
    user = (f'User needs: "{need}"\n'
            f"Free RAM budget: {budget_gb:.1f} GB\n\n"
            f"Catalog (name, size, uses, note):\n" + "\n".join(options))

    provider = key_info[0]
    if provider == "groq":
        url, model_id = "https://api.groq.com/openai/v1/chat/completions", config.GROQ_MODEL
    else:
        url, model_id = "https://openrouter.ai/api/v1/chat/completions", config.OPENROUTER_MODEL

    payload = {
        "model": model_id,
        "messages": [{"role": "system", "content": RECOMMEND_SYSTEM},
                      *conversation,
                      {"role": "user", "content": user}],
    }
    r = requests.post(url, timeout=90, json=payload,
                      headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        return None
    data = r.json()
    if "choices" not in data:
        return None
    return data["choices"][0]["message"]["content"].strip()


def fallback_recommend(description: str, budget_gb: float) -> dict:
    use = catalog.classify(description)
    picks = catalog.candidates_for(use, budget_gb, limit=2)
    return {"reply": f"Matched locally: this looks like a {use} job, and these "
                      f"fit your {budget_gb:.1f} GB.",
            "models": [{"name": m["name"], "why": m["note"]} for m in picks]}


def cloud_label() -> str:
    if config.PROXY_URL and not config.cloud_api_key():
        return "bean cloud"
    info = config.cloud_api_key()
    if not info:
        return "local matching"
    provider, _ = info
    return config.GROQ_MODEL if provider == "groq" else config.OPENROUTER_MODEL


# ---------------------------------------------------------------- download

def _stop_progress(progress) -> None:
    """progress.stop() can throw when there's no real terminal (CI, pipes) —
    rich's Live tries to enter the console context and fails. The bar is
    cosmetic; never let cleanup break the download result."""
    try:
        progress.stop()
    except Exception:
        pass


def download(name: str) -> bool:
    """ollama pull with a real progress bar — percent, speed, time left.

    Real ollama output is a mess of ANSI cursor moves (^[[A ^[[1G ^[[K) —
    frames aren't separated by \\r or \\n consistently. So instead of
    splitting records, we keep the recent tail of the stream and scan it for
    any percent/speed/ETA tokens, taking the max percent seen so far.
    """
    try:
        proc = subprocess.Popen(
            ["ollama", "pull", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, bufsize=0)
    except Exception as e:
        error(f"couldn't start download: {e}")
        return False

    progress = Progress(
        BarColumn(bar_width=None),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    )
    task = progress.add_task(f"pulling {name}", total=100)
    progress.start()
    last_pct = -1
    buf = b""
    tail_len = 8192  # the most recent frames always fit in here

    try:
        while True:
            chunk = proc.stderr.read(128)
            if not chunk:
                break
            buf = (buf + chunk)[-tail_len:]
            tail = buf

            pcts = re.findall(rb"\b(\d{1,3})%", tail)
            if pcts:
                pct = max(int(p) for p in pcts)
                if pct > last_pct:
                    progress.update(task, completed=pct)
                    last_pct = pct

            speeds = re.findall(rb"([\d.]+)\s*(MB/s|GB/s)", tail)
            desc = f"pulling {name}"
            if speeds:
                desc += f" · {speeds[-1][0].decode()}{speeds[-1][1].decode()}"
            progress.update(task, description=desc)

            if b"success" in tail:
                progress.update(task, completed=100)
    except BaseException:
        # Ctrl+C (or anything else) — never leave the bar frozen or an
        # orphaned pull behind.
        try:
            proc.kill()
        except Exception:
            pass
        _stop_progress(progress)
        console.print()
        error("download cancelled")
        return False
    finally:
        _stop_progress(progress)

    proc.wait()
    if proc.returncode != 0:
        error(f"download failed for {name}")
        return False
    if last_pct < 100:
        progress.update(task, completed=100)
    return True


# ---------------------------------------------------------------- handoff

def port_pids() -> list[int]:
    try:
        out = subprocess.run(["lsof", "-tiTCP:11434", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5).stdout
        return [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:
        return []


def clear_stray_daemon():
    """Kill any ollama daemon on 11434 that isn't the Ollama app's own —
    so the app can take the port when it starts. Same data dir, safe."""
    for pid in port_pids():
        try:
            comm = subprocess.run(["ps", "-o", "comm=", "-p", str(pid)],
                                  capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        except Exception:
            continue
        if "Ollama.app" in comm:
            continue
        status("stopping a leftover ollama daemon…")
        try:
            subprocess.run(["kill", str(pid)], timeout=5)
        except Exception:
            pass
        time.sleep(1)


def warm_model(model: str):
    """Load the model into RAM so it's ready the moment the app opens.

    Small num_ctx on purpose: the warm-up just pins the weights in memory
    with keep_alive. The app re-loads its own context when the user chats —
    but the weights stay, so the first message is instant, and we don't
    eat 17GB of RAM with a huge default context just to say hello."""
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags",
                                        timeout=2):
                break
        except Exception:
            time.sleep(0.5)
    try:
        payload = {"model": model, "prompt": "hi", "stream": False,
                   "keep_alive": "30m", "options": {"num_predict": 1,
                                                    "num_ctx": 2048}}
        req = urllib.request.Request(
            config.OLLAMA_API, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120):
            pass
    except Exception:
        pass  # non-fatal — the model is still in the app's list


def handoff_to_app(model: str) -> bool:
    """Open the Ollama app with the model ready. True if handed off."""
    if sys.platform == "darwin":
        if not Path("/Applications/Ollama.app").exists():
            error("the Ollama app isn't installed — grab it from "
                  "https://ollama.com/download")
            return False
        clear_stray_daemon()
        status("opening the Ollama app…")
        subprocess.run(["open", "-a", "Ollama"], timeout=10)
        with console.status("loading your model…", spinner="dots"):
            warm_model(model)
        console.print()
        success("your helper is ready — it's in the Ollama app")
        console.print()
        return True
    if sys.platform == "win32":
        try:
            os.startfile("ollama://")
        except Exception:
            # No handler for ollama:// means the desktop app isn't installed.
            error("the Ollama app isn't installed — grab it from "
                  "https://ollama.com/download")
            return False
        with console.status("loading your model…", spinner="dots"):
            warm_model(model)
        console.print()
        success("your helper is ready — it's in the Ollama app")
        console.print()
        return True
    # Linux: no desktop app — the terminal workshop takes over.
    status("no Ollama desktop app on Linux — but the model is ready")
    status(f"chat now with:  ollama run {model}")
    status("or stay right here in the terminal workshop:")
    console.print()
    return False


# ---------------------------------------------------------------- api key

PROVIDER_NAMES = {
    "groq": "Groq", "openrouter": "OpenRouter",
    "anthropic": "Anthropic", "openai": "OpenAI",
}


def detect_provider(key: str) -> str:
    k = key.strip()
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("sk-or-"):
        return "openrouter"
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("sk-"):
        return "openai"
    return "groq"


def key_screen() -> bool:
    """Shown once, when no key exists anywhere. Returns True if one was saved."""
    console.print()
    console.print("  [bold]Connect a cloud model[/bold] "
                   f"[{DIM}]— used once, to pick your local models[/{DIM}]")
    console.print()
    console.print(f"  [{DIM}]Free, no credit card:[/{DIM}]")
    console.print(f"  [{ACCENT}]●[/{ACCENT}] Groq        [{DIM}]console.groq.com/keys"
                   f"      · 1,000/day · doesn't train on your data[/{DIM}]")
    console.print(f"  [{ACCENT}]●[/{ACCENT}] OpenRouter  [{DIM}]openrouter.ai/keys"
                   f"         · 50/day[/{DIM}]")
    console.print()
    console.print(f"  [{DIM}]Paste your key below, or press enter to skip and let "
                   f"bean pick models offline.[/{DIM}]")
    console.print(f"  [{DIM}]Saved to ~/.localcoder/keys.json, readable only by you.[/{DIM}]")
    console.print()

    key = ask("paste your key (or enter to skip)")
    if not key:
        status("skipped — bean will match models locally")
        console.print()
        return False

    provider = detect_provider(key)
    config.save_key(provider, key)
    success(f"{PROVIDER_NAMES.get(provider, provider)} key saved"
            f" [{DIM}]· ~/.localcoder/keys.json[/{DIM}]")
    console.print()
    return True


# ---------------------------------------------------------------- main flow

def setup_flow() -> dict | None:
    # With the proxy configured, no key is needed — the shipped worker holds
    # it. The key screen is only for power users who want their own key.
    if not config.cloud_api_key() and not config.PROXY_URL:
        key_screen()
    banner()
    console.print(Panel(
        "Hey — I'm bean. I'll find you the right local model for your\n"
        "machine, download it, and hand you over to the Ollama app.\n\n"
        "Tell me what you'd like a helper for — or just say hi.\n",
        title="bean", border_style="grey35", expand=False))
    console.print()

    with console.status("checking your hardware…", spinner="dots"):
        setup_wizard.free_stray_ram(quiet=True)
        time.sleep(1)
        budget = onboard.ram_budget_gb()
    console.print()

    using_cloud = bool(config.cloud_api_key()) or bool(config.PROXY_URL)
    conversation: list[dict] = []
    rec = None
    cloud_source = None
    cloud_error = None
    t0 = time.time()

    # No cloud (no key, no proxy): one question, matched locally.
    if not using_cloud:
        need = ask("describe your use case")
        if not need:
            return None
        console.print()
        rec = fallback_recommend(need, budget)
        elapsed = time.time() - t0
    else:
        # Chat loop: the cloud model greets and talks normally; the moment
        # the user states a real need it replies with the recommendation
        # JSON, which is where this loop ends. Capped — if the model never
        # produces a recommendation, bean falls back to local matching
        # rather than chatting indefinitely. (Empty Enters don't count.)
        MAX_SETUP_TURNS = 12
        turns = 0
        while turns < MAX_SETUP_TURNS:
            msg = ask("you")
            if not msg:
                continue  # accidental Enter — just re-prompt
            if msg.lower() in ("exit", "quit", "q"):
                return None
            console.print()
            conversation.append({"role": "user", "content": msg})
            turns += 1

            text = None
            parsed = None
            with console.status("thinking…", spinner="dots"):
                try:
                    text = recommend_via_proxy(conversation, budget)
                    if text is None and using_cloud:
                        text = recommend(conversation, budget)
                    if text:
                        parsed = _parse_recommendation(text)
                except Exception as e:
                    # Never swallow this. A silent fallback once printed "No
                    # cloud key set" when the key was fine and the provider
                    # had rate-limited us.
                    cloud_error = f"{type(e).__name__}: {str(e)[:90]}"
                    break

            if parsed:
                rec = parsed
                cloud_source = "bean cloud" if config.PROXY_URL else cloud_label()
                elapsed = time.time() - t0
                break
            if cloud_error:
                status(f"cloud pick unavailable"
                       f"{' (' + cloud_error + ')' if cloud_error else ''}"
                       f" — matching locally instead")
                console.print()
                rec = fallback_recommend(msg, budget)
                elapsed = time.time() - t0
                break
            if not text:
                error("the cloud picker went quiet — matching locally instead")
                console.print()
                rec = fallback_recommend(msg, budget)
                elapsed = time.time() - t0
                break

            # Not a recommendation — a normal chat reply. Show it and keep
            # the conversation going.
            for line in text.strip().splitlines():
                console.print(f"  {line}")
            console.print()
            conversation.append({"role": "assistant", "content": text})

        if not rec:
            # The turn cap ran out without a recommendation (the model kept
            # chatting instead of picking). Don't hang or crash — fall back
            # to local matching.
            status("no model picked after a while — matching locally instead")
            console.print()
            msg = conversation[-1]["content"] if conversation else "a helper"
            rec = fallback_recommend(msg, budget)
            elapsed = time.time() - t0

    for line in rec["reply"].splitlines():
        console.print(f"  {line}")
    for m in rec["models"]:
        size = next((c["gb"] for c in catalog.CATALOG if c["name"] == m["name"]), 0)
        console.print(f"  [{ACCENT}]●[/{ACCENT}] [bold]{m['name']}[/bold] "
                       f"[{DIM}]· {size} GB · {m['why']}[/{DIM}]")
    console.print()
    meta("Setup", cloud_source or "local matching", elapsed)

    installed = []
    for m in rec["models"]:
        if setup_wizard.model_present(m["name"]):
            success(f"{m['name']} already installed")
            installed.append(m["name"])
        elif download(m["name"]):
            success(f"{m['name']} installed")
            installed.append(m["name"])
        else:
            error(f"{m['name']} download failed")
        if installed:
            break  # one working model is enough to get going
    console.print()

    if not installed:
        error("nothing installed.")
        console.print()
        return None

    # Cloud's job is done — everything after this is local only.
    status("cloud model done · from here everything runs on your machine")
    console.print()

    need = next((m["content"] for m in reversed(conversation)
             if m["role"] == "user"), "")
    profile = {"need": need, "models": installed, "model": installed[0]}
    onboard.save_profile(profile)
    return profile


# ---------------------------------------------------------------- chat

def chat(profile: dict):
    import local_worker
    model = profile["model"]
    config.CODING_SPECIALIST = model
    config.MODEL_TIERS = [(0.0, model)]

    console.print(f"  talking to [bold]{model}[/bold] "
                   f"[{DIM}]· fully local · type 'exit' to quit[/{DIM}]")
    console.print()

    while True:
        msg = ask("you")
        if not msg:
            continue  # accidental Enter — just re-prompt, don't bail
        if msg.lower() in ("exit", "quit", "q"):
            status("bye")
            console.print()
            return
        console.print()

        t0 = time.time()
        # Spinner while the model warms up; the moment the first token
        # arrives it switches to live streaming so the user sees the reply
        # forming instead of staring at a frozen spinner.
        spinner = console.status("thinking…", spinner="dots")
        spinner.start()
        buf = ""

        def show_token(tok: str):
            nonlocal buf
            spinner.stop()
            buf += tok
            # Flush complete lines as they form — console.print wraps them
            # to the terminal width, unlike raw console.out streaming.
            while "\n" in buf:
                line, rest = buf.split("\n", 1)
                console.print(line)
                buf = rest

        out = ""
        try:
            out = local_worker.stream(msg, "You are a helpful assistant. "
                                          "Answer clearly and concisely.",
                                      model=model, num_predict=700, timeout=300,
                                      on_token=show_token)
        except Exception as e:
            spinner.stop()
            out = f"(couldn't reach the local model: {type(e).__name__})"
        if buf:  # partial last line without a trailing newline
            console.print(buf)
        if not out and not buf:
            console.out("(no response)")
        console.print()
        console.print()
        meta("Local", model, time.time() - t0)
        console.print()


# ---------------------------------------------------------------- workshop

def workshop(profile: dict):
    """The workshop: the model thinks out loud and edits files.

    Same profile model, but with the full agent loop — a visible thinking
    panel, then real tool use (read/search/list files, run shell with your
    approval, edit files) until it has its answer.
    """
    import agent_loop
    model = profile["model"]

    console.print(f"  workshop · [bold]{model}[/bold]"
                   f"[{DIM}] · fully local · type 'exit' to quit[/{DIM}]")
    console.print(f"  [{DIM}]the model shows its thinking, can read and edit your "
                   f"files, and asks before running commands[/{DIM}]")
    console.print()

    while True:
        msg = ask("you")
        if not msg:
            continue  # accidental Enter — just re-prompt, don't bail
        if msg.lower() in ("exit", "quit", "q"):
            status("bye")
            console.print()
            return
        console.print()

        t0 = time.time()
        try:
            code, used_tools = agent_loop.run(msg, model)
            if used_tools:
                status("tools ran — edits shown above")
            elif code.strip():
                # no tools were needed: hand the answer over as a file
                slug = "_".join(re.findall(r"[a-zA-Z0-9]+", msg.lower())[:6]) or "task"
                out_path = Path.cwd() / f"{slug}.py"
                n = 2
                while out_path.exists():
                    out_path = Path.cwd() / f"{slug}_{n}.py"
                    n += 1
                out_path.write_text(code)
                status(f"wrote {out_path}")
        except Exception as e:
            error(f"workshop failed: {type(e).__name__}")
        meta("Local", model, time.time() - t0)
        console.print()


# ---------------------------------------------------------------- main

def main():
    profile = onboard.load_profile()
    if (profile is None or "--setup" in sys.argv
            or "models" not in (profile or {})
            or not setup_wizard.model_present(profile.get("model", ""))):
        profile = setup_flow()
        if not profile:
            return
    if "--workshop" in sys.argv:
        workshop(profile)
    elif "--chat" in sys.argv:
        chat(profile)
    elif handoff_to_app(profile["model"]):
        return
    else:
        console.print()
        workshop(profile)


if __name__ == "__main__":
    main()