"""The genuinely new piece — a bounded tool-use loop, not proven before tonight.

Falls back honestly to the plain single-shot path (local_worker.generate)
if it hits the iteration cap without producing final code, rather than
hanging or failing silently.
"""
import json
import re

import local_worker
import tools
import ui

MAX_ITERATIONS = 5


def run(task: str, model: str) -> tuple[str, bool]:
    """Returns (code, used_tools). used_tools=False signals the caller
    should treat this like the plain V1 path (no tool-loop overhead to report)."""

    plan_text = local_worker.plan(task, model=model)  # spinner shown inside local_worker.plan
    ui.thinking(plan_text)

    history = "(none yet)"
    created_this_session = set()
    used_tools = False
    consecutive_errors = 0
    step = 1

    while True:
        ui.step(step, MAX_ITERATIONS)
        response = local_worker.next_step(task, plan_text, history, model=model)

        if "FINAL_CODE:" in response:
            code = response.split("FINAL_CODE:", 1)[1].strip()
            return local_worker.strip_fences(code), used_tools

        tool_call = _parse_tool_call(response)
        if not tool_call:
            # model didn't follow the format — treat whatever it said as an
            # attempt at final code rather than looping on garbage
            ui.status_line("response didn't match expected format, treating as final code", kind="warn")
            return local_worker.strip_fences(response), used_tools

        used_tools = True
        name, args = tool_call["tool"], tool_call.get("args", {})
        ui.tool_call(name, args)

        result = _execute_tool(name, args, created_this_session)
        ui.tool_result(result)

        history += f"\n\n{name}({args}) -> {result}"

        if result.startswith("ERROR"):
            # A bad/hallucinated call (wrong args, unknown tool) is the
            # model's own mistake — let it see the error and retry the same
            # step instead of burning one of its steps on it. Bounded: two
            # consecutive failures means it's flailing, so fall back.
            consecutive_errors += 1
            if consecutive_errors >= 2:
                ui.status_line("the model keeps calling tools wrong — "
                               "falling back to a direct single-shot attempt", kind="warn")
                return local_worker.generate(task, model=model), used_tools
            ui.status_line("tool call failed — letting the model retry with "
                           "the error in context", kind="warn")
            continue

        consecutive_errors = 0
        step += 1
        if step > MAX_ITERATIONS:
            break

    ui.status_line(f"hit the {MAX_ITERATIONS}-step cap without final code — "
                    f"falling back to a direct single-shot attempt instead of hanging", kind="warn")
    return local_worker.generate(task, model=model), used_tools


def _parse_tool_call(response: str) -> dict | None:
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if "tool" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    return None


def _execute_tool(name: str, args: dict, created_this_session: set) -> str:
    if name == "edit_file":
        return tools.edit_file(args.get("path", ""), args.get("content", ""), created_this_session)
    fn = tools.TOOL_FUNCTIONS.get(name)
    if not fn:
        return f"ERROR: unknown tool '{name}'"
    import inspect
    sig = inspect.signature(fn)
    valid = set(sig.parameters)
    bad = set(args) - valid
    if bad:
        return (f"ERROR: bad arguments for {name} — unknown parameter(s) {sorted(bad)}. "
                f"{name} accepts: {', '.join(valid)}. Call it again with only valid arguments.")
    try:
        return fn(**args)
    except TypeError as e:
        return f"ERROR: bad arguments for {name}: {e}"
