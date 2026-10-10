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
        return text[:1000]


PROTOCOL = """Reply with JSON only, in ONE of these two shapes:
  {{"thought": "<one sentence: what you check and why>", "tool": "<tool name>", "args": {{...}}}}
  {{"thought": "<one sentence: your conclusion>", "final": {final_schema}}}
Rules: use only the listed tools; at most {max_steps} tool calls; check facts with tools instead of guessing;
your final answer must cite evidence taken from tool outputs or the given context.
IMPORTANT: you cannot call functions directly. To use a tool, write its name in the "tool" field of the JSON reply."""


class ReActAgent:
    def __init__(self, name, role, tools, final_schema, max_steps=5, offline=False, min_calls=2, starters=None):
        self.name, self.tools, self.max_steps, self.offline = name, tools, max_steps, offline
        # starters: list of (tool, args) run by CODE (read-only, no AI call) if the model wastes 3 steps in a row
        self.starters = starters or [(t.name, {}) for t in tools.values() if not t.args]   # default: tools needing no arguments
        self.min_calls = min_calls     # evidence rule: no final answer before this many tool calls
        self.system = f"You are {name}, {role}.\n" + PROTOCOL.format(
            final_schema=json.dumps(final_schema), max_steps=max_steps)

    def _gather(self, trace, seen):
        """The model keeps missing (unknown or repeated tools). Run the basic read-only checks ourselves so it can
        still answer from REAL evidence. Returns True if anything was gathered."""
        todo = [(n, a) for n, a in self.starters if n in self.tools and (n, json.dumps(a, sort_keys=True)) not in seen]
        if not todo:
            return False
        LIVE.event("warn", f"[{self.name}] the AI kept missing; gathering basic evidence with read-only tools")
        for n, a in todo[:self.max_steps]:
            seen.add((n, json.dumps(a, sort_keys=True)))
            LIVE.event("ai", f"[{self.name}] (code) calls {n}({json.dumps(a)})")
            trace.append({"step": 0, "thought": "evidence gathered by code", "tool": n, "args": a,
                          "observation": self.tools[n].run(a)})
        return True

    def run(self, goal, context):
        """Returns (final_answer_dict_or_None, trace)."""
        trace, seen, waste = [], set(), 0
        tool_list = "\n".join(f"- {t.name}({', '.join(t.args)}): {t.description}" for t in self.tools.values())
        LIVE.event("ai", f"[{self.name}] started: {goal}")
        for step in range(1, 2 * self.max_steps + 6):          # hard cap, even if the model misbehaves
            calls = sum(1 for t in trace if t["tool"] in self.tools)   # real tool calls only, not rejections
            last = calls >= self.max_steps
            user = (f"GOAL: {goal}\n\nCONTEXT:\n{json.dumps(context, default=str)[:3500]}"
                    f"\n\nAVAILABLE TOOLS (request one through the JSON reply):\n{tool_list}\n\nEVIDENCE SO FAR:\n"
                    + (json.dumps(trace)[-3500:] if trace else "nothing yet")
                    + ("\n\nTool budget used up. Give your final answer now." if last else ""))
            data, _ = ask_json(f"{self.name}_step{step}", self.system, user, offline=self.offline, max_tokens=700, tool_agent=True)
            if not data:
                LIVE.event("warn", f"[{self.name}] no AI answer available, stopping")
                return None, trace
            thought = str(data.get("thought", ""))[:300]
            if "final" in data and not last and calls < self.min_calls:
                LIVE.event("warn", f"[{self.name}] tried to conclude with {calls} tool call(s); evidence required, continuing")
                trace.append({"step": step, "thought": thought, "tool": None, "args": {},
                              "observation": f"REJECTED: you must call at least {self.min_calls} tools and cite their "
                                             f"output before giving a final answer. Call a tool now."})
                waste += 1
                if waste >= 3 and self._gather(trace, seen):
                    waste = 0
                continue
            if "final" in data or last:
                final = data.get("final") if isinstance(data.get("final"), dict) else None
                LIVE.event("ai", f"[{self.name}] conclusion: {thought}")
                return final, trace
            name = data.get("tool")
            args = data.get("args") if isinstance(data.get("args"), dict) else {}
            tool = self.tools.get(name)
            LIVE.event("ai", f"[{self.name}] thinks: {thought}")
            sig = (name, json.dumps(args, sort_keys=True, default=str))
            if tool and sig in seen:
                # same call again: do not run or count it, point the model back at the evidence it already has
                LIVE.event("warn", f"[{self.name}] repeated {name}({json.dumps(args)}), skipped")
                trace.append({"step": step, "thought": thought, "tool": None, "args": args,
                              "observation": f"You already called {name} with these arguments; the result is in the "
                                             f"evidence above. Call a DIFFERENT tool or give your final answer."})
                waste += 1
                if waste >= 3 and self._gather(trace, seen):
                    waste = 0
                continue
            if tool:
                waste = 0
                seen.add(sig)
                LIVE.event("ai", f"[{self.name}] calls {name}({json.dumps(args)})")
                obs = tool.run(args)
            else:
                LIVE.event("warn", f"[{self.name}] asked for unknown tool {name!r} with {json.dumps(args, default=str)[:150]}")
                obs = f"unknown tool '{name}'. Available tools: {sorted(self.tools)}"
                waste += 1
            trace.append({"step": step, "thought": thought, "tool": name, "args": args, "observation": obs})
            if waste >= 3 and self._gather(trace, seen):
                waste = 0
        return None, trace
