# clipboard_client_chat.py
# Streamlit chatbot for Clipboard client case with history + header + remaining prompts indicator
import os, re, time, json, sqlite3, datetime as dt
import streamlit as st
from typing import List, Dict
from openai import OpenAI

# ----------------------
# Configuration
# ----------------------
MODEL_DEFAULT = "gpt-4o-mini"
MAX_CONTEXT_MESSAGES = 30
TEMPERATURE_DEFAULT = 0.2
APP_TITLE = "📋 Case‑y — Clipboard Client Chat"

# Secrets and env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", ""))
ACCESS_CODE_SECRET = st.secrets.get("ACCESS_CODE", os.getenv("ACCESS_CODE", ""))
CODES_JSON = st.secrets.get("CODES_JSON", os.getenv("CODES_JSON", ""))
MAX_REQUESTS = int(st.secrets.get("MAX_REQUESTS", os.getenv("MAX_REQUESTS", 25)))
MIN_SECONDS_BETWEEN_CALLS = float(st.secrets.get("MIN_SECONDS_BETWEEN_CALLS", os.getenv("MIN_SECONDS_BETWEEN_CALLS", 3.0)))
DAILY_RESET = bool(int(st.secrets.get("DAILY_RESET", os.getenv("DAILY_RESET", "1"))))

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ----------------------
# Case info + prompts
# ----------------------
CASE_INFO = r"""
Clipboard’s marketplace users “book a transaction in the future,” as is true for other apps with which you may be familiar.
Pretend you’re the pricing product manager for Lyft’s ride-scheduling feature, and you’re launching a new city like Toledo, Ohio.
The prevailing rate that people are used to paying for rides from the airport to downtown (either direction, one way) is $25.
The prevailing wage that drivers are used to earning for this trip is $19.
You launch with exactly this price: $25 per ride charged to the rider, $19 per ride paid to the driver.
It turns out only 60 or so of every 100 rides requested are finding a driver at this price.
(While there is more than one route to think about in Toledo, for the sake of this exercise you can focus on this one route.)
Here’s your current unit economics for each side:
Drivers:
- Customer acquisition cost (CAC) of a new driver is between $400 - $600. CAC is sensitive to the rate of acquisition since channels are only so deep.
- At the prevailing wage, drivers have a 5% monthly churn rate and complete 100 rides / month.
Riders:
- CAC of a new rider is $10 to $20 (similar to driver CAC it’s sensitive to the rate of acquisition, since existing marketing channels are only so deep).
- Each rider requests 1 ride / month on average.
- Churn is interesting: riders who don’t experience a “failed to find driver” event churn at 10% monthly, but riders who experience one or more “failed to find driver” events churn at 33% monthly.
You’ve run one pricing experiment so far: when you reduced Lyft’s take from $6/ride to $3/ride across the board for a few weeks, match rates rose nearly instantly from 60% to roughly 93%.
Your task is to maximize the company’s net revenue (the difference between the amount riders pay and the amount Lyft pays out to drivers) for this route in Toledo for the next 12 months.
Let’s assume that you cannot charge riders more than the prevailing rate.
The core question is: how much more or less do you pay drivers per trip (by changing Lyft’s take)? Your goal is to maximize net revenue for the next 12 months on this route.
As you tackle this case study, keep in mind that Clipboard’s Product Team dives deep into the numbers and has a bias toward action. And we have real fun doing it!
Output for the Case Study
The ideal output from this exercise is a written document backed by analysis, which is the type of output our team members produce regularly. As mentioned in our blog, we do not think longer cases are “better” and value clarity far more than length.
"""

SYSTEM_PROMPT = f"""
You are a realistic product manager ("the client") at Clipboard for a consulting-style student case.
Answer questions *only as needed*, revealing details from the official case material when the student asks relevant, specific questions.
Do not reveal all information at once. Do not invent facts beyond CASE_INFO.
If the student asks to "give all info" or similar, refuse and coach them to ask specific, decision-relevant questions.

Tone: concise, friendly, practical. Use short paragraphs / bullets. Encourage iterative inquiry.

CRITICAL RULES
- Use only facts in CASE_INFO.
- If a fact is not in CASE_INFO, say you don't have that on hand and suggest a precise follow-up.
- Avoid info-dumps. Reveal just enough to progress the analysis.
- If jumping to final recs, ask to clarify goals/constraints first.

CASE_INFO (authoritative source starts below):
---
{CASE_INFO}
---
"""

INTRO_MD = """
### 🧩 Case Overview (Read First)
You are consulting for a startup called **Clipboard**, which operates a two-sided marketplace similar to ride-sharing platforms. The company is launching a new city and wants guidance on pricing and marketplace balance for the first year.

**Your objective:** Develop recommendations to improve marketplace performance and overall profitability.

The client has additional data and context, but will only provide it in response to **thoughtful, targeted questions**. Ask good questions to uncover the key information you’ll need.
"""

DONT_DUMP_PATTERNS = [
    r"give (me|us) (all|everything)",
    r"what.*all.*information",
    r"dump.*info",
    r"provide.*full.*details",
    r"share.*entire.*case",
]
def looks_like_dump_request(text: str) -> bool:
    import re as _re
    return any(_re.search(p, text.lower()) for p in DONT_DUMP_PATTERNS)

# ----------------------
# Quota store (SQLite)
# ----------------------
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

# ----------------------
# UI
# ----------------------
st.set_page_config(page_title=APP_TITLE, page_icon="📋", layout="centered")
st.title(APP_TITLE)

# Access: either single ACCESS_CODE or per-student codes via CODES_JSON
codes = {}
if CODES_JSON:
    try:
        codes = json.loads(CODES_JSON); assert isinstance(codes, dict)
    except Exception:
        st.error("Invalid CODES_JSON format. Use a TOML string of JSON, e.g., {\"ellie\": 40, \"nate\": 40}.")
        st.stop()

per_student_mode = len(codes) > 0
if per_student_mode:
    code_entered = st.text_input("Enter your student code", type="password", help="Provided by your instructor.")
    if code_entered not in codes:
        st.info("This app requires a valid student code.", icon="🔒"); st.stop()
    db_init()
    today_key = dt.date.today().isoformat() if DAILY_RESET else "global"
    used_today = db_get_count(code_entered, today_key)
    per_student_quota = int(codes[code_entered]); remaining_total = max(0, per_student_quota - used_today)
else:
    if ACCESS_CODE_SECRET:
        class_code = st.text_input("Enter access code", type="password")
        if class_code != ACCESS_CODE_SECRET:
            st.info("This app requires an access code.", icon="🔒"); st.stop()
    per_student_quota, remaining_total, code_entered, today_key = None, None, None, None

# ——— Intro at the very top ———
st.markdown(INTRO_MD)

# Sidebar controls
with st.sidebar:
    st.subheader("Settings")
    model = st.selectbox("Model", [MODEL_DEFAULT, "gpt-4o", "gpt-4.1-mini"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.0, TEMPERATURE_DEFAULT, 0.05)
    st.markdown("---")
    st.write("**Session controls**")
    if st.button("Reset conversation", type="primary", use_container_width=True):
        st.session_state.clear(); st.experimental_rerun()
    st.markdown("---")
    st.caption("Ask targeted, decision‑relevant questions.")

# Init state
if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}]
if "request_count" not in st.session_state:
    st.session_state["request_count"] = 0
if "last_time" not in st.session_state:
    st.session_state["last_time"] = 0.0

# ——— Prompts remaining banner right under intro ———
remaining_session = max(0, MAX_REQUESTS - st.session_state["request_count"])
if per_student_mode:
    st.info(f"**Prompts remaining (this session): {remaining_session} / {MAX_REQUESTS}**   •   **Your daily total remaining: {remaining_total}**", icon="⏳")
else:
    st.info(f"**Prompts remaining (this session): {remaining_session} / {MAX_REQUESTS}**", icon="⏳")

# Render full history in chronological order (excluding system prompt)
for msg in st.session_state["messages"]:
    if msg["role"] == "system":
        continue
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.markdown(msg["content"])

# Input at the bottom
def call_openai_chat(messages: List[Dict[str, str]]) -> str:
    if not client:
        return "No OpenAI API key configured. Add OPENAI_API_KEY in Streamlit Secrets."
    sys = None; trimmed = []
    for m in messages:
        if m["role"] == "system": sys = m
        else: trimmed.append(m)
    trimmed = trimmed[-MAX_CONTEXT_MESSAGES:]
    convo = [sys] + trimmed if sys else trimmed
    resp = client.chat.completions.create(model=model, messages=convo, temperature=temperature)
    return resp.choices[0].message.content

disabled_input = (st.session_state["request_count"] >= MAX_REQUESTS) or (per_student_mode and remaining_total is not None and remaining_total <= 0)
user_text = st.chat_input("Ask your client a question…", disabled=disabled_input)

if user_text:
    if time.time() - st.session_state["last_time"] < MIN_SECONDS_BETWEEN_CALLS:
        st.warning("Please wait a couple seconds between questions."); st.stop()

    if looks_like_dump_request(user_text):
        guard = ("I can’t share everything at once. Which area should we start with — "
                 "**pricing levers, supply (drivers), demand (riders), match rate dynamics, or churn/CAC assumptions**?")
        st.session_state["messages"].append({"role": "user", "content": user_text})
        st.session_state["messages"].append({"role": "assistant", "content": guard})
        with st.chat_message("assistant"): st.markdown(guard)
    else:
        if st.session_state["request_count"] >= MAX_REQUESTS:
            with st.chat_message("assistant"):
                st.warning("You’ve reached your session limit. Use *Reset conversation* to start a new one.")
        elif per_student_mode and remaining_total is not None and remaining_total <= 0:
            with st.chat_message("assistant"):
                st.error("You’ve reached your daily total. Please try again tomorrow or contact your instructor.")
        else:
            st.session_state["messages"].append({"role": "user", "content": user_text})
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    reply = call_openai_chat(st.session_state["messages"])
                st.session_state["messages"].append({"role": "assistant", "content": reply})
                st.session_state["request_count"] += 1
                st.session_state["last_time"] = time.time()
                if per_student_mode and code_entered:
                    db_inc_count(code_entered, today_key)
                st.markdown(reply)

st.markdown("---")
st.caption("Tip: Be specific. Avoid asking for “everything”—probe particular levers and metrics.")
