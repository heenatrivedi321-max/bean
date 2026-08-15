# bean

One command. Tell bean what you need a helper for — a writing buddy, a coding
assistant, a model to think things through — and it picks the right local
model for your machine, downloads it in front of you, then opens the Ollama
app with your model already loaded. Everything runs on your computer.

## Try it

```bash
curl -fsSL https://raw.githubusercontent.com/heenatrivedi321-max/bean/main/install.sh | bash
```

Or from a clone:

```bash
./install.sh
```

Windows? Same story, one command (PowerShell):

```powershell
curl -fsSL https://raw.githubusercontent.com/heenatrivedi321-max/bean/main/install.ps1 | powershell -Command -
```

That's it. Say hi, chat a bit, then type what you need — bean picks the best
model that fits (through a tiny proxy that holds the key — no API keys
required from you), downloads it with a live progress bar, then steps out.
The Ollama app opens with your model ready to chat.

install.sh also puts a `bean` command on your PATH, so next time it's just:

```bash
bean
```

After that, bean is just your model-finder. Chatting lives in the Ollama
app, fully local and private.

## How it works

- `bean.py` — the whole journey: greet & chat → hardware check → model pick
  → download with progress → handoff to the Ollama app
- `worker/` — the Cloudflare Worker proxy that holds the Groq key
  server-side, so no key ever ships to users
- `catalog.py` — the curated model catalog; picks the smallest model that
  fits your need and RAM, preferring anything already installed (instant
  setup)
- `install.sh` — the one-command front door: installs Python deps and
  Ollama if missing, starts it, opens bean

## Power-user flags

```bash
python3 bean.py --workshop   # terminal agent: shows its thinking, reads and
                             # edits your files, asks before running commands
python3 bean.py --chat       # plain terminal chat, no tools
python3 bean.py --setup      # force re-setup (pick a new model)
```

## Requirements

- macOS, Windows, or Linux
- Ollama installed (install.sh / install.ps1 does it for you)
- On macOS the Ollama desktop app opens with your model ready; on Windows
  the desktop app opens too; on Linux (no desktop app) the terminal
  workshop takes over and the model is one `ollama run` away

## For developers

```bash
pip install -r requirements.txt
python3 bean.py
```

The only time anything leaves your machine is the single model-picking call
at setup (one short prompt through the worker proxy). Everything after that
runs locally.