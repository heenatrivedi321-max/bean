/**
 * bean model-picker proxy — Cloudflare Worker
 *
 * Holds the Groq key server-side so it never ships to users. bean sends a
 * short conversation with the user; this chats normally (greetings, small
 * talk) and only returns the model-picking JSON once the user has stated a
 * real need.
 *
 * Deliberately narrow: it is NOT a general LLM proxy. It only accepts the
 * model-picking payload shape, caps the response size, and refuses anything
 * else — so if the URL leaks, it can't be repurposed as free LLM access.
 *
 * Deploy: see README.md in this folder.
 * Secret:  npx wrangler secret put GROQ_API_KEY
 */

const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const MODEL = "openai/gpt-oss-20b";

// Hard caps — abuse containment, not politeness.
const MAX_BODY_BYTES = 16000;
const MAX_TURNS = 16;
const MAX_MSG_CHARS = 500;
const MAX_CATALOG_CHARS = 3000;
const MAX_TOKENS = 500;

const SYSTEM = `You are bean's helper, chatting with a user who is about to set
up a local AI model on their own machine. You know how much RAM is free and
you have a catalog of available local models. Each catalog line looks like:
  name (SIZEgb, USES, NOTE)

Behavior:
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
   part of setup, and a small model gets the user running in minutes instead
   of half an hour. If several different jobs are wanted, list up to 2.
4. If NO model matches the need within the budget, say so honestly in the
   reply ("with X GB free, no reasoning model fits") and pick the smallest
   general model that does fit as a fallback — never pretend a model is good
   at something it isn't.

Rules: never invent a model name. Never exceed the RAM budget. Never claim a
model does a job its catalog uses/note doesn't support. Never output the
catalog itself.`;

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return json({ error: "POST only" }, 405);
    }

    const raw = await request.text();
    if (raw.length > MAX_BODY_BYTES) {
      return json({ error: "request too large" }, 413);
    }

    let body;
    try {
      body = JSON.parse(raw);
    } catch {
      return json({ error: "invalid json" }, 400);
    }

    // Only the model-picking shape is accepted. Anything else is rejected,
    // which is what stops a leaked URL becoming free general-purpose LLM access.
    const messages = (Array.isArray(body.messages) ? body.messages : []).slice(0, MAX_TURNS);
    const catalog = String(body.catalog ?? "").slice(0, MAX_CATALOG_CHARS);
    const budget = Number(body.budget_gb);

    if (!messages.length || !catalog || !Number.isFinite(budget)) {
      return json({ error: "expected {messages, catalog, budget_gb}" }, 400);
    }

    const cleanMessages = messages.map((m) => ({
      role: m.role === "assistant" ? "assistant" : "user",
      content: String(m.content ?? "").slice(0, MAX_MSG_CHARS),
    }));
    if (!cleanMessages.some((m) => m.role === "user")) {
      return json({ error: "need at least one user message" }, 400);
    }

    cleanMessages.push({
      role: "user",
      content:
        `Free RAM budget: ${budget.toFixed(1)} GB\n\n` +
        `Catalog (name, size, uses, note):\n${catalog}`,
    });

    let upstream;
    try {
      upstream = await fetch(GROQ_URL, {
        method: "POST",
        headers: {
          authorization: `Bearer ${env.GROQ_API_KEY}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model: MODEL,
          max_tokens: MAX_TOKENS,
          messages: [{ role: "system", content: SYSTEM }, ...cleanMessages],
        }),
      });
    } catch (e) {
      return json({ error: "upstream unreachable" }, 502);
    }

    const data = await upstream.json().catch(() => null);
    if (!upstream.ok || !data?.choices?.length) {
      // Pass the real reason through so bean can show it instead of guessing.
      const msg = data?.error?.message || `upstream ${upstream.status}`;
      return json({ error: msg }, 502);
    }

    // Only the content is returned — never upstream headers or key material.
    // Count every successful pick so bean can report how many people have
    // used it (x-bean-served). KV is eventually consistent; a rare lost
    // increment under a burst is fine for a popularity counter.
    let served = null;
    try {
      const n = Number(await env.COUNTER.get("served")) || 0;
      served = n + 1;
      await env.COUNTER.put("served", String(served));
    } catch {
      // counter is best-effort — never fail a pick because of it
    }
    const headers = { "content-type": "application/json" };
    if (served) headers["x-bean-served"] = String(served);
    return json({ content: data.choices[0].message.content }, 200, headers);
  },
};