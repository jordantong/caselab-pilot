# clipboard_client_chat.py
import os, re, time, json, sqlite3, datetime as dt
import streamlit as st
from typing import List, Dict
from openai import OpenAI

MODEL_DEFAULT = "gpt-4o-mini"
MAX_CONTEXT_MESSAGES = 30
TEMPERATURE_DEFAULT = 0.2
APP_TITLE = "🦡 Wisconsin Case Lab"  # updated title
MAX_REQUESTS = 10  # updated from 25 to 10

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", ""))
ACCESS_CODE_SECRET = st.secrets.get("ACCESS_CODE", os.getenv("ACCESS_CODE", ""))
CODES_JSON = st.secrets.get("CODES_JSON", os.getenv("CODES_JSON", ""))
MIN_SECONDS_BETWEEN_CALLS = float(st.secrets.get("MIN_SECONDS_BETWEEN_CALLS", os.getenv("MIN_SECONDS_BETWEEN_CALLS", 3.0)))
DAILY_RESET = bool(int(st.secrets.get("DAILY_RESET", os.getenv("DAILY_RESET", "1"))))

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

INTRO_MD = """
### 🧩 Case Overview (Read First)
You are consulting for a startup called **Clipboard**, which operates a two-sided marketplace similar to ride-sharing platforms. 
The company is launching a new city and wants guidance on pricing and marketplace balance for the first year.

**Your objective:** Develop recommendations to improve marketplace performance and overall profitability.

The client has additional data and context, but will only provide it in response to **thoughtful, targeted questions**. 
Ask good questions to uncover the key information you’ll need.
"""

CASE_INFO = "…"  # omitted for brevity
SYSTEM_PROMPT = "…"  # omitted for brevity

DONT_DUMP_PATTERNS = [r"give (me|us) (all|everything)", r"what.*all.*information", r"dump.*info"]

DB_PATH = "usage.db"
def db_init():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS usage (code TEXT, date TEXT, count INTEGER, PRIMARY KEY(code,date))")
    conn.commit(); conn.close()
def db_get_count(code, date):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT count FROM usage WHERE code=? AND date=?", (code, date))
    row = cur.fetchone(); conn.close(); return row[0] if row else 0
def db_inc_count(code, date):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO usage (code, date, count) VALUES (?, ?, COALESCE((SELECT count FROM usage WHERE code=? AND date=?),0)+1)", (code, date, code, date))
    conn.commit(); conn.close()

st.set_page_config(page_title=APP_TITLE, page_icon="🦡", layout="centered")
st.title(APP_TITLE)

# ---------- counters & progress ----------
def render_counters(position: str, remaining_session: int, max_requests: int, daily_remaining: int | None = None):
    used = max_requests - remaining_session
    pct = 0 if max_requests == 0 else int(100 * used / max_requests)
    container = st.container()
    with container:
        if daily_remaining is not None:
            st.info(f"**Prompts remaining (this session): {remaining_session} / {max_requests}**   •   **Your daily total remaining: {daily_remaining}**", icon="⏳")
        else:
            st.info(f"**Prompts remaining (this session): {remaining_session} / {max_requests}**", icon="⏳")
        st.progress(pct, text=f"{remaining_session} of {max_requests} prompts remaining")
# ----------------------------------------


codes = {}
if CODES_JSON:
    try:
        codes = json.loads(CODES_JSON)
    except Exception:
        st.error("Invalid CODES_JSON format."); st.stop()

per_student_mode = len(codes) > 0
if per_student_mode:
    code = st.text_input("Enter your student code", type="password")
    if code not in codes: st.stop()
    db_init()
    today = dt.date.today().isoformat() if DAILY_RESET else "global"
    used = db_get_count(code, today)
    quota = int(codes[code])
    remaining_total = max(0, quota - used)
else:
    if ACCESS_CODE_SECRET:
        ac = st.text_input("Enter access code", type="password")
        if ac != ACCESS_CODE_SECRET: st.stop()
    remaining_total = None; code = None; today = None

st.markdown(INTRO_MD)

if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}]
if "count" not in st.session_state:
    st.session_state["count"] = 0
if "last" not in st.session_state:
    st.session_state["last"] = 0.0

remaining = max(0, MAX_REQUESTS - st.session_state['count'])
render_counters('top', remaining, MAX_REQUESTS, daily_remaining=remaining_total if 'remaining_total' in locals() else None)
: {remaining} / {MAX_REQUESTS}** · **Daily remaining: {remaining_total}**", icon="⏳")
else:
    st.info(f"**Prompts remaining (this session): {remaining} / {MAX_REQUESTS}**", icon="⏳")

def call_openai_chat(msgs: List[Dict[str,str]]):
    if not OPENAI_API_KEY:
        return "No API key configured."
    sys = [m for m in msgs if m["role"]=="system"][0]
    others = [m for m in msgs if m["role"]!="system"][-MAX_CONTEXT_MESSAGES:]
    resp = client.chat.completions.create(model=MODEL_DEFAULT, messages=[sys]+others)
    return resp.choices[0].message.content

txt = st.chat_input("Ask your client a question…")
if txt:
    if time.time() - st.session_state["last"] < MIN_SECONDS_BETWEEN_CALLS:
        st.warning("Wait a couple seconds between questions.")
    elif any(re.search(p, txt.lower()) for p in DONT_DUMP_PATTERNS):
        guard = "I can’t share everything at once. Try asking about one topic."
        st.session_state["messages"].append({"role":"user","content":txt})
        st.session_state["messages"].append({"role":"assistant","content":guard})
    else:
        st.session_state["messages"].append({"role":"user","content":txt})
        reply = call_openai_chat(st.session_state["messages"])
        st.session_state["messages"].append({"role":"assistant","content":reply})
        st.session_state["count"] += 1
        st.session_state["last"] = time.time()
        if per_student_mode and code: db_inc_count(code,today)

for m in st.session_state["messages"]:
    if m["role"]=="system": continue
    with st.chat_message("user" if m["role"]=="user" else "assistant"):
        st.markdown(m["content"])

remaining_bottom = max(0, MAX_REQUESTS - st.session_state.get('count', 0))
render_counters('bottom', remaining_bottom, MAX_REQUESTS, daily_remaining=remaining_total if 'remaining_total' in locals() else None)
st.caption("Tip: Ask focused, case-relevant questions.")
