# App (Streamlit chat UI)

A chat page in the browser for the **analyst agent** (`pipeline/agents/analyst.py`), with saved chat history.

## Run it

1. Docker up, with data loaded and dbt built (see `data/README.md`):
   ```bash
   docker compose up -d
   ```
2. `OPENAI_API_KEY` in `.env` (see `pipeline/README.md`).
3. From the **repo root**:
   ```bash
   streamlit run app/streamlit_app.py
   ```
4. It opens at **http://localhost:8501**. Stop it with `Ctrl+C` in the terminal.

Streamlit reloads when you save `streamlit_app.py`: click **Rerun** at the top right of the page (or choose "Always rerun").

## What's on the page

| Part | Does |
|---|---|
| **Chat** | Ask a question, get the answer (tables are shown as tables). An empty chat shows three example questions as buttons. |
| **Live status box** | While the agent works, each Cube query appears as it runs. |
| **"Data used (n Cube queries)"** | Under every answer: exactly which tools were called with which values, so every number can be traced back. |
| **Sidebar: ➕ New chat** | Starts an empty chat. |
| **Sidebar: History** | Saved chats, newest first, titled by their first question. Click one to reopen it; 🗑 deletes it. |

**Follow-up questions work.** The agent gets the whole conversation, so "And how much capacity is missing in its worst quarter?" refers to the component asked about before.

## Where the chats are saved

One JSON file per chat in `app/chats/`, for example:

```json
{
  "id": "a5ae2abf3bae",
  "title": "Explain what is happening with AC 366413968.",
  "created": "2026-11-01T20:41:12",
  "messages": [
    {"role": "user", "content": "Explain what is happening with AC 366413968."},
    {"role": "assistant", "content": "AC 366413968 is **high** severity...",
     "tool_calls": [{"name": "get_component_timeline", "args": {"ac_code": "366413968"}}]}
  ]
}
```

The folder is **gitignored**, so your chats stay on your machine. Delete the folder to clear all history.

## How the code is organised (`streamlit_app.py`)

1. **Chat storage**: `new_chat`, `save_chat`, `list_chats`, `delete_chat` (plain JSON files).
2. **`answer()`**: adds the question, calls `run()` from the analyst agent, shows tool calls live, saves the chat.
3. **Page**: sidebar (new chat, history), the messages, the input box.

Streamlit re-runs the whole script on every click. The open chat is kept between runs in `st.session_state.chat`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `streamlit: command not found` | Activate the venv (`source .venv/bin/activate`), or install it: `uv pip install -r requirements.txt`. |
| "⚠️ The agent failed: ... Connection" in the chat | Cube isn't running: `docker compose up -d`. |
| "⚠️ The agent failed: ... AuthenticationError" | `OPENAI_API_KEY` in `.env` is missing or wrong. |
| `Port 8501 is already in use` | Another Streamlit is running. Stop it, or use `streamlit run app/streamlit_app.py --server.port 8502`. |
| Answers are slow | Each question makes 1–12 Cube queries plus LLM calls; a broad question ("which components...") takes the longest. |
