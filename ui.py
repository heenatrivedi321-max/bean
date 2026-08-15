"""Real terminal UI using `rich` — live spinners during actual wait time
(not fake animation), colored panels for model selection and the agent's
stated thinking, formatted tool calls. Built on top of the existing plain
print-based flow, not a replacement for it — every function here degrades
to something reasonable if called outside its normal flow.
"""
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def model_selection(ram_gb: float, model: str, cleaned_gb: float = 0.0):
    lines = []
    if cleaned_gb > 0:
        lines.append(f"[yellow]cleaned up ~{cleaned_gb:.1f} GB from leftover processes[/yellow]")
    ram_color = "green" if ram_gb >= 6 else ("yellow" if ram_gb >= 2 else "red")
    lines.append(f"free RAM: [{ram_color}]{ram_gb:.1f} GB[/{ram_color}]")
    lines.append(f"selected model: [bold cyan]{model}[/bold cyan]")
    console.print(Panel("\n".join(lines), title="hardware check", border_style="blue", expand=False))


def thinking(plan_text: str):
    console.print(Panel(plan_text, title="[bold magenta]thinking[/bold magenta]",
                         border_style="magenta", expand=False))


def tool_call(name: str, args: dict):
    console.print(f"  [cyan]→ tool call:[/cyan] [bold]{name}[/bold]({args})")


def tool_result(result: str):
    preview = result[:150] + ("..." if len(result) > 150 else "")
    console.print(f"    [dim]{preview}[/dim]")


def status_line(msg: str, kind: str = "info"):
    colors = {"info": "white", "pass": "green", "fail": "red", "warn": "yellow"}
    color = colors.get(kind, "white")
    console.print(f"[{color}]{msg}[/{color}]")


def step(current: int, total: int):
    console.print(f"  [cyan]step {current}/{total}[/cyan]")


def spinner(message: str):
    """Use as: `with ui.spinner('generating...'):` — a real live spinner
    for the actual duration of a blocking call, not a canned animation."""
    return console.status(f"[bold green]{message}[/bold green]", spinner="dots")
