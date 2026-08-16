# What it looks like

A real setup, from a fresh machine. One command, no API keys:

```
$ curl -fsSL https://raw.githubusercontent.com/heenatrivedi321-max/bean/main/install.sh | bash
bean › bean isn't here yet — grabbing it from https://github.com/heenatrivedi321-max/bean.git
bean › installed the 'bean' command (~/.local/bin/bean)
bean › everything's in place
bean › opening bean

╭──────────────────────────── bean ────────────────────────────╮
│ Hey — I'm bean. I'll find you the right local model for your │
│ machine, download it, and hand you over to the Ollama app.   │
│                                                              │
│ Tell me what you'd like a helper for — or just say hi.       │
╰──────────────────────────────────────────────────────────────╯

  you  i need a python coding buddy
⠋ thinking…

  For coding help, I've picked a model that fits your RAM and can assist with
  Python tasks. This should get you coding quickly and efficiently.
  ● qwen2.5-coder:7b · 4.7 GB · it's the strongest coder under 4.8 GB
  ▪ Setup · bean cloud · 1.0s
  ✓ qwen2.5-coder:7b already installed
  cloud model done · from here everything runs on your machine
  opening the Ollama app…
⠋ loading your model…

  ✓ your helper is ready — it's in the Ollama app
```

If the model isn't installed yet, you get a live progress bar during the
download instead of the "already installed" line. After that, everything runs
on your machine — chat in the Ollama app, fully local and private.