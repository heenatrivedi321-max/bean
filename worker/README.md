# bean model-picker proxy

Holds the Groq key server-side so it never ships inside bean.

**Status: deployed.** https://bean-picker.bean-picker.workers.dev

## Deploy (free, ~3 minutes, no credit card)

```bash
cd worker
npx wrangler login          # opens browser, sign in / sign up
npx wrangler secret put GROQ_API_KEY   # paste your gsk_... key when prompted
npx wrangler deploy
```

Wrangler prints a URL like `https://bean-picker.<you>.workers.dev`.
It's already wired in as the default in `config.py` (`PROXY_URL`); override
with `export BEAN_PROXY_URL="..."` or edit `config.py`.

## Free tier

100,000 requests/day. bean makes **one** call per user turn, at setup — so
that's 100k+ new setups per day before you'd pay anything.

## Why this is safe if the URL leaks

The worker only accepts `{messages, catalog, budget_gb}` and only ever asks
the model to pick from a supplied catalog, capped at 500 output tokens. It is
not a general-purpose LLM proxy — the system prompt steers it to model-picking,
turns and output are capped, so a leaked URL can't be resold as free inference.
It can still be *spammed*, so add a Cloudflare rate-limit rule on the route if
that ever happens.
