"""Chat UI for the analyst agent, with saved chat history.

Run from the repo root, with Docker (Postgres + Cube) up:
    streamlit run app/streamlit_app.py

Each chat is saved as one JSON file in app/chats/ (gitignored), so chats survive a restart.
"""
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

# `streamlit run` only puts app/ on the import path; the agent lives in pipeline/ at the repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.agents.analyst import run  # noqa: E402

CHATS_DIR = ROOT / "app" / "chats"
EXAMPLES = [
    "Which components are most saturated?",
    "Explain what is happening with AC 366413968.",
    "What changed for AC 369576663 since the last snapshot?",
]


# --- Chat storage: one JSON file per chat ---------------------------------------------

def new_chat() -> dict:
    return {"id": uuid.uuid4().hex[:12], "title": "New chat",
            "created": datetime.now().isoformat(timespec="seconds"), "messages": []}


def save_chat(chat: dict) -> None:
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    (CHATS_DIR / f"{chat['id']}.json").write_text(json.dumps(chat, indent=2, ensure_ascii=False))


def list_chats() -> list[dict]:
    """Saved chats, newest first."""
    chats = [json.loads(path.read_text()) for path in CHATS_DIR.glob("*.json")]
    return sorted(chats, key=lambda chat: chat["created"], reverse=True)


def delete_chat(chat_id: str) -> None:
    (CHATS_DIR / f"{chat_id}.json").unlink(missing_ok=True)


# --- UI -------------------------------------------------------------------------------

def show_tool_calls(tool_calls: list[dict]) -> None:
    if tool_calls:
        with st.expander(f"Data used ({len(tool_calls)} Cube queries)"):
            for call in tool_calls:
                st.code(f"{call['name']}({call['args']})", language="python")


def answer(chat: dict, question: str) -> None:
    """Add the question, run the agent with live tool-call updates, save the answer."""
    chat["messages"].append({"role": "user", "content": question})
    if chat["title"] == "New chat":
        chat["title"] = question[:60]
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        tool_calls, reply = [], ""
        with st.status("Querying Cube…", expanded=False) as status:
            try:
                for kind, value in run([{"role": m["role"], "content": m["content"]} for m in chat["messages"]]):
                    if kind == "tool":
                        tool_calls.append(value)
                        status.write(f"→ `{value['name']}` {value['args']}")
                    else:
                        reply = value
                status.update(label=f"Done ({len(tool_calls)} Cube queries)", state="complete")
            except Exception as error:   # Cube down, OpenAI error, ...: show it, keep the chat
                status.update(label="Failed", state="error")
                reply = f"⚠️ The agent failed: `{error}`\n\nIs Docker running (`docker compose up -d`)?"
        st.markdown(reply)

    chat["messages"].append({"role": "assistant", "content": reply, "tool_calls": tool_calls})
    save_chat(chat)


st.set_page_config(page_title="Sourcing Pilot · Analyst", page_icon="📦", layout="wide")

if "chat" not in st.session_state:
    st.session_state.chat = new_chat()
chat = st.session_state.chat

with st.sidebar:
    st.title("📦 Sourcing Pilot")
    if st.button("➕ New chat", use_container_width=True):
        st.session_state.chat = new_chat()
        st.rerun()

    st.subheader("History")
    saved = list_chats()
    if not saved:
        st.caption("No saved chats yet.")
    for item in saved:
        open_col, delete_col = st.columns([5, 1])
        is_current = item["id"] == chat["id"]
        if open_col.button(item["title"], key=f"open-{item['id']}", use_container_width=True,
                           type="primary" if is_current else "secondary"):
            st.session_state.chat = item
            st.rerun()
        if delete_col.button("🗑", key=f"delete-{item['id']}", help="Delete this chat"):
            delete_chat(item["id"])
            if is_current:
                st.session_state.chat = new_chat()
            st.rerun()

st.header("Capacity analyst")
st.caption("Answers from the Cube semantic layer (saturation mart). Every number comes from a Cube query.")

for message in chat["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        show_tool_calls(message.get("tool_calls", []))

question = st.chat_input("Ask about capacity saturation…")
if not chat["messages"] and not question:
    st.write("Try one of these:")
    for example in EXAMPLES:
        if st.button(example):
            question = example

if question:
    answer(chat, question)
    st.rerun()
