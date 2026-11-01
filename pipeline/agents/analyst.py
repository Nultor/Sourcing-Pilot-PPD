"""Analyst agent v1 (README §4.3): answers capacity-saturation questions by reading Cube.

A free agent: the LLM decides which Cube tools to call, in a loop, until it can answer.

    agent (LLM) ──wants a tool──► tools (CUBE_TOOLS) ──results──► agent ... ──done──► answer

Run from the repo root, with Docker (Postgres + Cube) up:
    python -m pipeline.agents.analyst "Which components breach capacity, and how severe is each?"

The model is OPENAI_MODEL in .env (default below); the key is OPENAI_API_KEY.
"""
import os
import sys
from collections.abc import Iterator
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from pipeline.tools.cube import CUBE_TOOLS

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
DEFAULT_MODEL = "gpt-5.4-mini"

# The severity rules are the ones the data generator labels its planted cases with
# (data_gen/saturation.py, classify), so the answers can be checked against the ground truth.
SYSTEM_PROMPT = """\
You are a capacity analyst for a packaging sourcing team. You answer questions about
capacity saturation of packaging components (AC codes) using the Cube tools only.

Definitions
- Saturation = forecast demand / capacity, per forecast quarter (3-year horizon).
- Baseline: baseline demand on the lines in use today. Stretch: stretch (high) demand on
  baseline capacity plus the spare capacity of qualified contract manufacturers (CMs).
- A quarter is "over threshold" when saturation > 0.85 (warning). Above 1.0 is critical.

Severity of a component (apply exactly, using its quarter-by-quarter timeline)
- none: baseline saturation never above 0.85.
- temporary_spike: baseline above 0.85 in exactly one quarter.
- high: baseline above 0.85 in two or more quarters, and stretch above 0.85 in two or more
  quarters (even every qualified CM is not enough).
- early_warning: baseline above 0.85 in two or more quarters, stretch not (fewer than two),
  and the first baseline breach is the 5th forecast quarter or later.
- medium: every other case with baseline above 0.85 in two or more quarters.
First breach quarter = the first forecast quarter with baseline saturation above 0.85.

How to work
- Prefer the named tools (get_top_saturated, get_component_timeline, compare_snapshots).
  Use list_metrics + query_metric only when no named tool fits.
- Peak values from get_top_saturated only tell you which components to look at; decide
  severity and first breach from get_component_timeline.
- Only state numbers that a tool returned. Never estimate or invent numbers. If the data
  can't answer the question, say so.
- Be concise: lead with the answer, then the supporting numbers per component.
"""


def build_graph(model: str | None = None):
    llm = ChatOpenAI(model=model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)).bind_tools(CUBE_TOOLS)

    def agent(state: MessagesState) -> dict:
        return {"messages": [llm.invoke([SystemMessage(SYSTEM_PROMPT)] + state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(CUBE_TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)   # tool calls → "tools", else → end
    graph.add_edge("tools", "agent")
    return graph.compile()


def run(history: list[dict]) -> Iterator[tuple[str, dict | str]]:
    """Run the agent on a conversation and yield its steps as they happen.

    history: [{"role": "user" | "assistant", "content": str}, ...], ending with the new question.
    Yields ("tool", {"name": ..., "args": ...}) for each tool call, then ("answer", text).
    """
    messages = [HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]) for m in history]
    answer = ""
    for update in build_graph().stream({"messages": messages}, stream_mode="updates"):
        for message in update.get("agent", {}).get("messages", []):
            for call in message.tool_calls:
                yield "tool", {"name": call["name"], "args": call["args"]}
            answer = message.content
    yield "answer", answer


def ask(question: str) -> str:
    """Run the agent on one question, print each tool call, return the final answer."""
    for kind, value in run([{"role": "user", "content": question}]):
        if kind == "tool":
            print(f"  → {value['name']}({value['args']})")
        else:
            return value


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(ask(sys.argv[1]))
