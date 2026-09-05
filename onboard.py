"""First-run setup: describe your use case, get models that actually work.

The differentiator: every other picker reads your RAM and consults a spec
sheet. This one downloads the shortlist and *benchmarks them on your machine*
before recommending. Tonight proved spec sheets lie — mistral-nemo "fits"
16GB and runs at 28 seconds per token; gpt-oss:20b "fits" and runs at 0.47
tokens/sec. Only running them tells the truth.
"""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import catalog
import config
import setup_wizard

PROFILE_PATH = config.HOME_DIR / "profile.json"

# A small real task per use case — used to time the model AND check it
# produces something usable, not just tokens.
BENCH_TASKS = {
    "coding": ("Write a Python function that reverses a string. Output only code.",
               lambda out: "def" in out),
    "writing": ("Write one clear sentence explaining what a database is.",
                lambda out: len(out.split()) >= 5),
    "reasoning": ("If a train travels 60 km in 1.5 hours, what is its speed? "
                  "Answer briefly.", lambda out: "40" in out),
    "vision": ("Describe what you would look for in a photo of a receipt.",
               lambda out: len(out.split()) >= 5),
    "chat": ("Say hello in one short sentence.", lambda out: len(out.strip()) > 0),
    "general": ("Say hello in one short sentence.", lambda out: len(out.strip()) > 0),
}


def load_profile() -> dict | None:
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text())
        except Exception:
            return None
    return None


def save_profile(profile: dict):
    config.ensure_dirs()
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))


# ------------------------------------------------------- per-need memory
#
# The "ongoing relationship" idea: bean shouldn't just pick a model once at
# setup and stop there. If you needed a coding model this morning and a
# writing model this afternoon, switching back to coding tonight shouldn't
# mean re-running the whole chat-and-benchmark flow again -- bean already
# knows what worked. Stored inside profile.json under "by_need" so it
# travels with the same file, not a second source of truth.

def remember_model_for_need(use_case: str, model: str):
    profile = load_profile() or {}
    by_need = profile.get("by_need", {})
    by_need[use_case] = model
    profile["by_need"] = by_need
    save_profile(profile)


def recall_model_for_need(use_case: str) -> str | None:
    profile = load_profile() or {}
    return profile.get("by_need", {}).get(use_case)


def classify_use_case(description: str) -> str:
    """Use the cloud model if a key exists, else keyword matching."""
    key_info = config.cloud_api_key()
    if not key_info:
        return catalog.classify(description)
    try:
        import cloud_orchestrator
        prompt = (f"A user describes what they want a local AI model for:\n\n"
                  f"\"{description}\"\n\n"
                  f"Reply with EXACTLY ONE word from this list and nothing else: "
                  f"coding, writing, reasoning, vision, chat")
        raw = cloud_orchestrator.semantic_audit("classify", prompt) or ""
        word = raw.strip().lower().split()[-1].strip(".,`*")
        if word in catalog.USE_CASE_KEYWORDS:
            return word
    except Exception:
        pass
    return catalog.classify(description)


def pull_model(name: str) -> bool:
    result = subprocess.run(["ollama", "pull", name],
                             capture_output=True, text=True, timeout=1800)
    return result.returncode == 0


def benchmark(model: str, use_case: str, timeout: int = 120) -> dict:
    """Run a real task and measure it. This is the whole point — a model that
    'fits' but generates at 0.5 tok/s is useless, and only running it reveals that."""
    task, is_valid = BENCH_TASKS.get(use_case, BENCH_TASKS["general"])
    payload = {"model": model, "prompt": task, "stream": False,
               "options": {"num_predict": 120}}
    req = urllib.request.Request(
        config.OLLAMA_API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception as e:
        return {"model": model, "ok": False, "tps": 0.0,
                "reason": type(e).__name__.replace("Error", " error").lower()}

    elapsed = time.time() - t0
    out = data.get("response", "")
    n = data.get("eval_count", 0)
    dur = data.get("eval_duration", 0)
    tps = (n / dur * 1e9) if dur else (n / elapsed if elapsed else 0)

    if not is_valid(out):
        return {"model": model, "ok": False, "tps": round(tps, 1),
                "reason": "output wasn't usable"}
    if tps < 2.0:
        return {"model": model, "ok": False, "tps": round(tps, 1),
                "reason": "too slow to use"}
    return {"model": model, "ok": True, "tps": round(tps, 1), "reason": ""}


def ram_budget_gb() -> float:
    """Leave real headroom — the model plus its context has to fit alongside
    everything else running."""
    available = setup_wizard.free_ram_gb()
    if available < 0:
        return 4.0
    return max(1.0, available - 1.0)
