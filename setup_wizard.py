"""First-run setup: check free RAM, pull the proven coding specialist if missing."""
import json
import re
import subprocess
import time
import urllib.request

import config
import ui


def running_model_processes() -> list[str]:
    """Real check, not a guess — same `ps aux | grep llama-server` pattern
    used to diagnose the actual lingering-process problem tonight.

    The Ollama desktop app runs its own llama-server while a model is loaded;
    those are in use, not stray, so they're excluded. Only processes that
    aren't owned by the app get flagged for cleanup."""
    try:
        out = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5).stdout
        return [line for line in out.splitlines()
                if "llama-server" in line and "/Ollama.app/" not in line]
    except Exception:
        return []


def free_stray_ram(quiet: bool = False) -> bool:
    """Proactively kills any lingering model processes before even checking
    RAM — confirmed tonight this is very often the actual cause of tightness,
    not unrelated apps. Returns True if anything was actually cleaned up."""
    stray = running_model_processes()
    if not stray:
        return False
    if not quiet:
        ui.status_line(f"found {len(stray)} leftover model process(es) — cleaning up...", kind="warn")
    try:
        subprocess.run(["pkill", "-f", "llama-server"], capture_output=True, timeout=10)
        time.sleep(1)
        subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True, timeout=10)
    except Exception:
        pass
    return True


def free_ram_gb() -> float:
    """Available memory on macOS — NOT just `Pages free`.

    Confirmed bug: counting only free pages reported 1.58 GB when 5.74 GB was
    genuinely available, which kept forcing a fallback to the weak 3B model
    on a machine that could comfortably run the 7B. Inactive, speculative and
    purgeable pages are all reclaimable on demand, so they count as available.
    """
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
        page_size = 16384  # matches this machine; parsed below if reported
        m = re.search(r"page size of (\d+) bytes", out)
        if m:
            page_size = int(m.group(1))

        counts = {}
        for line in out.splitlines():
            m = re.match(r"Pages (free|inactive|speculative|purgeable):\s+(\d+)", line)
            if m:
                counts[m.group(1)] = int(m.group(2))

        available_pages = sum(counts.get(k, 0) for k in
                               ("free", "inactive", "speculative", "purgeable"))
        return (available_pages * page_size) / (1024 ** 3)
    except Exception:
        return -1  # unknown, don't block on a failed check


def model_present(model_name: str) -> bool:
    try:
        req = urllib.request.Request(config.OLLAMA_TAGS_API)
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.load(r)
        names = [m["name"] for m in data.get("models", [])]
        return model_name in names
    except Exception:
        return False


def run_setup(quiet: bool = False) -> str | None:
    """Picks the right model tier for current free RAM, ensures it's pulled,
    and returns its name — or None on failure. Re-checks RAM every call
    (not cached at startup) since a chat session's free RAM can genuinely
    change between tasks, and tonight proved that matters."""
    config.ensure_dirs()

    reclaimed_gb = 0.0
    if quiet:
        ram_before = free_ram_gb()
        cleaned = free_stray_ram(quiet=True)
        ram = free_ram_gb() if cleaned else ram_before
        if 0 <= ram < config.MIN_FREE_RAM_GB:
            time.sleep(2)
            ram = free_ram_gb()
        model = config.pick_model_for_ram(ram)
    else:
        with ui.spinner("checking hardware..."):
            ram_before = free_ram_gb()
            cleaned = free_stray_ram(quiet=True)
            if cleaned:
                time.sleep(1)  # let the OS actually reclaim memory before re-measuring
                ram = free_ram_gb()
                reclaimed_gb = ram - ram_before if ram_before >= 0 else 0
            else:
                ram = ram_before
            # Genuine memory pressure can be transient — give it one real
            # second chance to settle before accepting a critically low
            # reading, rather than scaring the user over a blip.
            if 0 <= ram < config.MIN_FREE_RAM_GB:
                time.sleep(2)
                ram = free_ram_gb()
            model = config.pick_model_for_ram(ram)

        ui.model_selection(ram if ram >= 0 else 0.0, model, cleaned_gb=reclaimed_gb)
        if 0 <= ram < config.MIN_FREE_RAM_GB:
            ui.status_line(
                f"{ram:.1f} GB free after cleanup and a settle check — this is a real "
                f"system limit I can't fix myself (other apps, not leftover model "
                f"processes). Proceeding with the lightest model tier anyway.", kind="warn")

    if model_present(model):
        return model

    if not quiet:
        ui.status_line(f"pulling {model} (first run only)...", kind="info")
    result = subprocess.run(["ollama", "pull", model])
    return model if result.returncode == 0 else None
