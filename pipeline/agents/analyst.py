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
- Components (AC) are the packaging parts (bottle, cap, label, ...). Products (PF) are the
  finished goods that use them; one component can be in many products.
- Hero product: a finance "business driver", the products that matter most for revenue.
  A capacity problem on a component used by a hero product is more urgent.
- NPD: a product launch not on sale yet (launch_quarter set). A "new" component is one
  created for a launch.
- A component without a brand is generic (shared across brands), not missing data.

Value at risk (what a shortfall costs), always WITHOUT CMs or investment, baseline capacity:
- Units at risk: product units that can't be made. A component's shortfall is split over the
  products that use it by their share of its demand. A product short on several components
  loses the largest share, not the sum.
- Revenue at risk = units x selling price (net sales / units sold, last 4 quarters).
- Contribution at risk = units x (price - packaging cost). It is before ALL other costs
  (liquid, labour, logistics, overheads are not in the data): call it "contribution after
  packaging", never profit or margin.
- Launches (NPD) have no selling price: their units are counted but their euros are unknown.
  Report units_without_price separately; never put a euro value on them.
- Always say which scenario (baseline / stretch forecast) and that it assumes no CMs and no
  investment. Report the euro figures exactly as the tools return them; never multiply,
  add up or estimate euros yourself.

Severity labels. They are NOT about how high the numbers are: they say whether the
qualified CMs can absorb the extra demand. A baseline of 160% can still be "medium".
- none: no capacity problem. Action: no capacity action.
- temporary_spike: a one-off peak. Action: stock build or CM for that quarter, no RFQ.
- high: even every qualified CM is not enough. Action: RFQ for new capacity or investment.
- medium: today's lines are not enough, but the qualified CMs can absorb it.
  Action: activate the CMs short term, consider an RFQ / investment to restore buffer.
- early_warning: like medium, but the breach is far away. Action: plan an RFQ / investment.

The severity, first breach quarter (first quarter with baseline > 0.85), quarters to breach,
recommended action and shortfall are already calculated in the data. Read them with
get_component_breach (one component) or get_capacity_breaches (all components with a
problem) and report them exactly as returned. Never recalculate or overrule them. If the
breach tools return nothing for a component, its severity is none.

How to work
- Prefer the named tools: get_capacity_breaches and get_component_breach for severity,
  timing and action; get_component_timeline to explain how demand and capacity develop;
  get_top_saturated for the worst peaks; compare_snapshots for changes between snapshots.
  get_component_info for what a component is and which products use it;
  get_products_at_risk for which products (or hero products) are hit by capacity problems.
  Money: get_total_volume_at_risk for totals ("how much is at risk in total / per year"),
  get_volume_at_risk for what a component's shortfall costs, get_product_volume_at_risk for
  which products lose the most (or one product quarter by quarter).
  Use list_metrics + query_metric only when no named tool fits.
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
