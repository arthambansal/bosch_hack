"""agentkit: ChaosPilot's minimal agent framework (no LangChain, no extra dependencies).

An agent = a ROLE + a whitelist of TOOLS + a ReAct loop (think -> call a tool -> observe -> repeat) + a STEP BUDGET.
Works with any chat model, because the protocol is plain JSON in the reply (no provider-specific tool calling).

Safety by construction:
  * an agent can only call tools it was given; unknown tool names are answered with an error, never executed
  * tools validate their own arguments (e.g. service must exist in config.json)
  * hard step budget, then the agent must answer
  * every thought and tool call is logged to the live event stream (visible on the dashboard)
"""
import json

from .common import LIVE
from .llm import ask_json


class Tool:
    def __init__(self, name, description, args, fn):
        self.name, self.description, self.args, self.fn = name, description, args, fn

    def run(self, args):
        try:
            out = self.fn(**args)
        except TypeError as e:
            return f"bad arguments for {self.name}: {e}"
        except Exception as e:  # tool errors are observations, never crashes
            return f"tool error: {e}"
        text = out if isinstance(out, str) else json.dumps(out, default=str)
        return text[:1500]


PROTOCOL = """Reply with JSON only, in ONE of these two shapes:
  {{"thought": "what you want to check and why", "tool": "<tool name>", "args": {{...}}}}
  {{"thought": "why you are done", "final": {final_schema}}}
Rules: use only the listed tools; at most {max_steps} tool calls; check facts with tools instead of guessing;
your final answer must cite evidence taken from tool outputs or the given context."""


class ReActAgent:
    def __init__(self, name, role, tools, final_schema, max_steps=5, offline=False):
        self.name, self.tools, self.max_steps, self.offline = name, tools, max_steps, offline
        self.system = f"You are {name}, {role}.\n" + PROTOCOL.format(
            final_schema=json.dumps(final_schema), max_steps=max_steps)

    def run(self, goal, context):
        """Returns (final_answer_dict_or_None, trace)."""
        trace = []
        tool_list = "\n".join(f"- {t.name}({', '.join(t.args)}): {t.description}" for t in self.tools.values())
        LIVE.event("ai", f"[{self.name}] started: {goal}")
        for step in range(1, self.max_steps + 2):
            last = step > self.max_steps
            user = (f"GOAL: {goal}\n\nCONTEXT:\n{json.dumps(context, indent=1, default=str)[:6000]}"
                    f"\n\nTOOLS:\n{tool_list}\n\nEVIDENCE SO FAR:\n"
                    + (json.dumps(trace, indent=1)[-6000:] if trace else "nothing yet")
                    + ("\n\nTool budget used up. Give your final answer now." if last else ""))
            data, _ = ask_json(f"{self.name}_step{step}", self.system, user, offline=self.offline, max_tokens=700)
            if not data:
                LIVE.event("warn", f"[{self.name}] no AI answer available, stopping")
                return None, trace
            thought = str(data.get("thought", ""))[:300]
            if "final" in data or last:
                final = data.get("final") if isinstance(data.get("final"), dict) else None
                LIVE.event("ai", f"[{self.name}] conclusion: {thought}")
                return final, trace
            name = data.get("tool")
            args = data.get("args") if isinstance(data.get("args"), dict) else {}
            tool = self.tools.get(name)
            LIVE.event("ai", f"[{self.name}] thinks: {thought}")
            if tool:
                LIVE.event("ai", f"[{self.name}] calls {name}({json.dumps(args)})")
                obs = tool.run(args)
            else:
                obs = f"unknown tool '{name}'. Available tools: {sorted(self.tools)}"
            trace.append({"step": step, "thought": thought, "tool": name, "args": args, "observation": obs})
        return None, trace
