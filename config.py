"""Paths, model config, and cloud API key detection."""
import os
from pathlib import Path

HOME_DIR = Path.home() / ".localcoder"
RUNS_DIR = HOME_DIR / "runs"
MEMORY_FILE = HOME_DIR / "memory.json"

OLLAMA_API = "http://localhost:11434/api/generate"
OLLAMA_TAGS_API = "http://localhost:11434/api/tags"

CODING_SPECIALIST = "qwen2.5-coder:7b"  # default/fallback when RAM can't be checked

# Hardware-tiered model selection. Both are the same specialist family (only
# one proven reliable at coding tonight), just scaled down for tighter RAM —
# not guessing among untested different models, only sizing the trusted one.
# The 7B is 4.7 GB on disk. The old 6.0 threshold was set against a broken
# RAM reading that undercounted available memory by ~3x, so this machine kept
# falling back to the weak 3B unnecessarily. 5.2 leaves real context headroom.
MODEL_TIERS = [
    (5.2, "qwen2.5-coder:7b"),   # the specialist that actually performed tonight
    (0.0, "qwen2.5-coder:3b"),   # genuinely constrained machines only
]

MIN_FREE_RAM_GB = 5.2

# Ollama defaults to the model's max context (llama3.2's is 131072 — that's
# 17GB of RAM for a 2GB model). Cap it: plenty for chat and tool loops,
# without silently eating a machine's memory.
DEFAULT_NUM_CTX = 8192


def pick_model_for_ram(free_ram_gb: float) -> str:
    """Picks the largest model tier the current free RAM can support.
    free_ram_gb < 0 means unknown — default to the safer, smaller model."""
    if free_ram_gb < 0:
        return "qwen2.5-coder:3b"
    for threshold, model in MODEL_TIERS:
        if free_ram_gb >= threshold:
            return model
    return MODEL_TIERS[-1][1]

MAX_RETRIES = 2  # matches the capped retry pattern that worked all night


# The audit call is short (a few hundred tokens), so a strong model here
# costs very little per run — and tonight proved judgment is exactly where
# capability matters most. Override with LOCALCODER_CLOUD_MODEL.
# Defaults to a genuinely large FREE model — verified to catch a local-model
# failure that passed local verification ("build a sign up page" -> a Flask
# installer, reported Done; this model flagged all 5 requirements missing).
# Paid frontier models work too: set LOCALCODER_CLOUD_MODEL=anthropic/claude-sonnet-5
OPENROUTER_MODEL = os.environ.get(
    "LOCALCODER_CLOUD_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")


# Groq's free tier: 1,000 requests/day, no credit card, and — unlike Gemini —
# it does not train on your prompts, which matters for a tool that promises
# privacy. Preferred over OpenRouter's 50/day free cap.
GROQ_MODEL = os.environ.get("LOCALCODER_GROQ_MODEL", "llama-3.3-70b-versatile")


# Shipped default: a Cloudflare Worker that holds the Groq key server-side,
# so no key is embedded in the distributed code. Users can override with their
# own key (see cloud_api_key), and if this is unset bean matches models locally.
PROXY_URL = os.environ.get(
    "BEAN_PROXY_URL",
    "https://bean-picker.bean-picker.workers.dev")

KEYS_FILE = HOME_DIR / "keys.json"

PROVIDER_ENV = [
    ("groq", "GROQ_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
]


def _saved_keys() -> dict:
    if not KEYS_FILE.exists():
        return {}
    try:
        import json
        return json.loads(KEYS_FILE.read_text())
    except Exception:
        return {}


def save_key(provider: str, key: str):
    """Stored at ~/.localcoder/keys.json with owner-only permissions (0600),
    the same convention as ~/.aws/credentials."""
    import json
    ensure_dirs()
    keys = _saved_keys()
    keys[provider] = key
    KEYS_FILE.write_text(json.dumps(keys, indent=2))
    try:
        KEYS_FILE.chmod(0o600)
    except Exception:
        pass


def cloud_api_key() -> tuple[str, str] | None:
    """Environment variables win; otherwise fall back to the saved key file."""
    for provider, env_var in PROVIDER_ENV:
        if os.environ.get(env_var):
            return (provider, os.environ[env_var])
    saved = _saved_keys()
    for provider, _ in PROVIDER_ENV:
        if saved.get(provider):
            return (provider, saved[provider])
    return None


def ensure_dirs():
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
