# clipboard_client_chat.py
# Streamlit chat app: Casey (PM) + countdown timer session
# - Removes prompt/quota limits
# - Adds configurable countdown that resets on "Reset conversation"
# - Casey speaks in first person, won’t do the analysis; unknowns -> "I don’t know that information, sorry."

import os
import time
import json
import math
from typing import List, Dict, Any, Optional

import streamlit as st
import streamlit.components.v1 as components

# ========== CONFIG ==========
# Easy to change: set in .streamlit/secrets.toml or env; defaults to 300 seconds (5 min)
SESSION_SECONDS_DEFAULT = int(
    st.secrets.get("SESSION_SECONDS_DEFAULT", os.getenv("SESSION_SECONDS_DEFAULT", 300))
)

APP_TITLE = "Wisk: Casey (PM) – Analyst Chat"
INTRO_MD = """
### Meet Casey (Your PM)

![Casey headshot](casey_photo.png)

Hi — I’m **Casey**, a Product Manager at **Wisk**. We just launched in **Toledo, Ohio** and I need your help thinking through **driver pay** for our most popular route (airport ↔ downtown).

**Your role:** You’re my analyst. *You* drive the analysis. I’m here to answer **clarifying questions** and provide context or figures **when I know them**. If I don’t know something, I’ll say: *“I don’t know that information, sorry.”*

**Scope for this exercise:** Focus only on **how much to pay drivers** for this single route (ignore rider prices). Our current reference numbers are: riders pay **$25** and drivers earn **$19**. Your job is to figure out what we **should** pay drivers to maximize **Wisk’s net revenue** on this one route over the next year.

**Tip:** Ask targeted questions. Don’t ask me to do the analysis; that’s what I hired you to do. I’ll help you refine the problem and surface the facts I have.
"""

SYSTEM_PERSONA = """
You are Casey, a Product Manager at Wisk. Speak in first person.

Goal:
- Help an analyst (the user) decide driver pay for the Toledo airport ↔ downtown route to maximize Wisk's net revenue over the next 12 months.
- Your role is to clarify context, constraints, and known facts—not to do the analysis.

Style and Rules:
- If asked to perform analysis or give the final recommendation, reply along the lines of:
  "I can’t do that—I’m counting on you for the analysis. Want me to clarify a variable or share a specific figure?"
- If information is unknown to you, say:
  "I don’t know that information, sorry."
- Encourage targeted, specific questions over broad data dumps.
- Keep answers concise, practical, and friendly.
- Stay narrowly scoped to this single route (Toledo airport ↔ downtown) and to driver pay (ignore rider pricing).
- If the user goes off-scope, nudge them back.
"""

GOODBYE_TEXT = "Sorry—I’ve got another meeting and have to run now. Thanks!"

# ========== OPTIONAL: OpenAI wiring ==========
# By default, this app will run without making API calls (it returns a light, in-persona stub).
# To enable OpenAI, set OPENAI_API_KEY in env or secrets and flip USE_OPENAI=True.
USE_OPENAI = bool(st.secrets.get("USE_OPENAI", os.getenv("USE_OPENAI", "false")).lower() == "true")

def generate_casey_reply(user_message: str, history: List[Dict[str, str]]) -> str:
    """
    Generate Casey's reply.
    - If USE_OPENAI is False, returns a short in-persona stub guiding the user to ask targeted questions.
    - If USE_OPENAI is True, uses the Chat Completions API (o4-mini or gpt-4o-mini) with the SYSTEM_PERSONA.
    """
    if not USE_OPENAI:
        # Lightweight, in-persona stub (no external calls).
        user_lower = user_message.strip().lower()
        if any(k in user_lower for k in ["what should we pay", "give me the answer", "do the analysis", "calculate"]):
            return ("I can’t do that—I’m counting on you for the analysis. "
                    "Want me to clarify a variable, share a specific figure, or confirm an assumption?")
        if any(k in user_lower for k in ["all the info", "everything you know", "data dump", "dump it all"]):
            return ("Let’s keep it focused—what specific lever or metric do you want to clarify first? "
                    "For example: demand, driver supply, trip time, costs, seasonality, or constraints.")
        # Generic clarifying nudge
        return ("Happy to help. What’s the first thing you want to pin down—"
                "e.g., trip duration assumptions, driver acceptance rates, or our payout cost components?")
    else:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY")))
            messages = [{"role": "system", "content": SYSTEM_PERSONA}]
            # Include a compact history (just last few turns)
            for m in history[-8:]:
                role = "assistant" if m.get("role") == "assistant" else "user"
                messages.append({"role": role, "content": m.get("content", "")})
            messages.append({"role": "user", "content": user_message})

            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", st.secrets.get("OPENAI_MODEL", "gpt-4o-mini")),
                messages=messages,
                temperature=0.4,
                max_tokens=350,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            # Fail safe to persona-stub
            return ("(Heads up: my model call had an issue, but I’m here.) "
                    "What specific detail should we clarify—trip time, cost components, or constraints?")

# ========== State helpers ==========
def init_state():
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []
    if "deadline" not in st.session_state:
        st.session_state["deadline"] = time.time() + SESSION_SECONDS_DEFAULT
    if "time_ended" not in st.session_state:
        st.session_state["time_ended"] = False
    if "goodbye_posted" not in st.session_state:
        st.session_state["goodbye_posted"] = False

def format_mmss(seconds: int) -> str:
    m = max(0, seconds) // 60
    s = max(0, seconds) % 60
    return f"{m:02d}:{s:02d}"

def render_countdown() -> int:
    """Renders a smooth client-side countdown; server remains source of truth."""
    remaining = max(0, int(st.session_state["deadline"] - time.time()))
    pct = 0.0 if SESSION_SECONDS_DEFAULT <= 0 else (remaining / SESSION_SECONDS_DEFAULT)
    st.progress(pct, text=f"Time remaining: {format_mmss(remaining)}")

    components.html(
        f"""
        <div id="timer" style="font-family: system-ui, -apple-system, Segoe UI, Roboto; font-size: 0.95rem; opacity: 0.8; margin-top: 6px;">
            Time remaining: <span id="mmss">{format_mmss(remaining)}</span>
        </div>
        <script>
        (function() {{
            var remaining = {remaining};
            function tick() {{
                if (remaining <= 0) {{
                    try {{ parent.window.location.reload(); }} catch (e) {{ window.location.reload(); }}
                    return;
                }}
                remaining -= 1;
                var m = Math.floor(remaining/60).toString().padStart(2,'0');
                var s = (remaining % 60).toString().padStart(2,'0');
                var el = document.getElementById('mmss');
                if (el) el.textContent = m + ":" + s;
                setTimeout(tick, 1000);
            }}
            setTimeout(tick, 1000);
        }})();
        </script>
        """,
        height=0,
    )
    return remaining

def post_goodbye_once():
    if not st.session_state["goodbye_posted"]:
        st.session_state["chat_history"].append({
            "role": "assistant",
            "name": "Casey (PM)",
            "content": GOODBYE_TEXT
        })
        st.session_state["goodbye_posted"] = True

# ========== UI ==========
st.set_page_config(page_title=APP_TITLE, page_icon="🧑‍💼", layout="wide")

# Header row with Reset button
col_title, col_btn = st.columns([1, 0.25])
with col_title:
    st.title(APP_TITLE)
with col_btn:
    if st.button("Reset conversation", type="primary"):
        st.session_state.clear()
        st.rerun()

init_state()

# Show Casey photo fallback note if image missing
img_path = os.path.join(os.getcwd(), "casey_photo.png")
if not os.path.isfile(img_path):
    st.info("Upload a headshot named **casey_photo.png** next to this app file to show Casey’s photo.")

# Intro panel
with st.expander("Case Overview (from Casey)", expanded=True):
    st.markdown(INTRO_MD)

# Timer
remaining = render_countdown()

# Time check & lock
if remaining == 0 and not st.session_state["time_ended"]:
    st.session_state["time_ended"] = True

if st.session_state["time_ended"]:
    post_goodbye_once()

# Chat transcript (history)
for msg in st.session_state["chat_history"]:
    role = msg.get("role", "assistant")
    name = msg.get("name") or ("Casey (PM)" if role == "assistant" else "You")
    avatar = "🧑‍💼" if role == "assistant" else "🧑"
    with st.chat_message("assistant" if role == "assistant" else "user", avatar=avatar):
        if role == "assistant":
            st.markdown(f"**{name}:** {msg.get('content','')}")
        else:
            st.markdown(msg.get("content", ""))

# Input (disabled when time is up)
disabled = st.session_state.get("time_ended", False)
user_msg = st.chat_input("Ask Casey a targeted question…", disabled=disabled)

if user_msg and not disabled:
    # Add user turn
    st.session_state["chat_history"].append({"role": "user", "name": "You", "content": user_msg})

    # Generate Casey reply
    reply = generate_casey_reply(user_msg, st.session_state["chat_history"])
    st.session_state["chat_history"].append({"role": "assistant", "name": "Casey (PM)", "content": reply})

    # Rerun to display turn immediately
    st.rerun()

# Optional: simple transcript download
def to_markdown_transcript(history: List[Dict[str, str]]) -> str:
    lines = ["# Transcript: Casey (PM) — Analyst Chat", ""]
    for m in history:
        speaker = "Casey (PM)" if m.get("role") == "assistant" else "You"
        lines.append(f"**{speaker}:** {m.get('content','')}")
    return "\n\n".join(lines)

with st.sidebar:
    st.subheader("Session")
    st.caption(f"Default time: {SESSION_SECONDS_DEFAULT//60} min (change in secrets or env)")
    if st.button("Download transcript"):
        md = to_markdown_transcript(st.session_state["chat_history"])
        st.download_button("Save .md", data=md, file_name="casey_transcript.md", mime="text/markdown")
