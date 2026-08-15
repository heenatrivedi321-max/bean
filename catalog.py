"""Curated model catalog — real Ollama models, with honest size figures.

Deliberately small and hand-picked rather than "every model on the hub".
Tonight proved spec sheets lie (mistral-nemo "fits" 16GB and runs at 28
seconds per token), so the catalog only carries models worth benchmarking,
and the benchmark decides the winner — not this table.
"""

# gb = actual download size. Keep these honest; they gate what gets tried.
CATALOG = [
    # --- coding ---
    {"name": "qwen2.5-coder:1.5b", "gb": 1.0, "uses": ["coding"], "note": "tiny coder"},
    {"name": "qwen2.5-coder:3b",   "gb": 1.9, "uses": ["coding"], "note": "light coder"},
    {"name": "qwen2.5-coder:7b",   "gb": 4.7, "uses": ["coding"], "note": "strong coder"},
    {"name": "qwen2.5-coder:14b",  "gb": 9.0, "uses": ["coding"], "note": "large coder"},
    {"name": "deepseek-coder-v2:16b", "gb": 8.9, "uses": ["coding"], "note": "MoE coder"},

    # --- general / writing / chat ---
    {"name": "llama3.2:3b",  "gb": 2.0, "uses": ["writing", "chat", "general"], "note": "light general"},
    {"name": "gemma2:9b",    "gb": 5.4, "uses": ["writing", "chat", "general"], "note": "good writer"},
    {"name": "qwen2.5:7b",   "gb": 4.7, "uses": ["writing", "chat", "general"], "note": "solid all-round"},
    {"name": "qwen2.5:14b",  "gb": 9.0, "uses": ["writing", "chat", "general"], "note": "large general"},

    # --- reasoning / analysis ---
    {"name": "deepseek-r1:8b",  "gb": 5.2, "uses": ["reasoning", "math"], "note": "thinks step by step"},
    {"name": "deepseek-r1:14b", "gb": 9.0, "uses": ["reasoning", "math"], "note": "larger reasoner"},

    # --- vision ---
    {"name": "llava:7b",  "gb": 4.7, "uses": ["vision", "images"], "note": "reads images"},
    {"name": "llava:13b", "gb": 8.0, "uses": ["vision", "images"], "note": "larger vision"},
]

USE_CASE_KEYWORDS = {
    "coding":    ["code", "coding", "program", "script", "python", "javascript", "dev",
                  "software", "app", "function", "debug", "api", "backend", "frontend"],
    "writing":   ["write", "writing", "blog", "essay", "article", "copy", "email",
                  "story", "content", "draft"],
    "reasoning": ["reason", "logic", "analys", "think", "math", "solve", "research"],
    "vision":    ["image", "vision", "picture", "photo", "screenshot", "ocr", "visual"],
    "chat":      ["chat", "assistant", "talk", "conversation", "companion", "general"],
}


def classify(description: str) -> str:
    """Keyword fallback when no cloud model is available to classify."""
    text = description.lower()
    scores = {use: sum(1 for k in words if k in text)
              for use, words in USE_CASE_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def candidates_for(use_case: str, budget_gb: float, limit: int = 3,
                   smallest_first: bool = True) -> list[dict]:
    """Models matching the use case that fit the RAM budget.

    Smallest-first by default: the download is the slowest part of setup, so
    the smallest fitting model gets the user running fastest. Pass
    smallest_first=False for a largest-first shortlist when benchmarking.
    """
    matches = [m for m in CATALOG
               if use_case in m["uses"] and m["gb"] <= budget_gb]
    if not matches:  # nothing fits the use case, fall back to anything that fits
        matches = [m for m in CATALOG if m["gb"] <= budget_gb]
    matches.sort(key=lambda m: m["gb"] if smallest_first else -m["gb"])
    return matches[:limit]
