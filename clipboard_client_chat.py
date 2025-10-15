# clipboard_client_chat.py
# Wisconsin Case Lab interactive client simulation (no sidebar + printable transcript + Option A reset)

import os, re, time, json, sqlite3, datetime as dt, unicodedata
from typing import List, Dict
import streamlit as st
from openai import OpenAI

APP_TITLE = "Wisconsin Case Lab"
MODEL_DEFAULT = "gpt-4o-mini"
MAX_CONTEXT_MESSAGES = 30
TEMPERATURE_DEFAULT = 0.2
MAX_REQUESTS = 10

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", ""))
ACCESS_CODE_SECRET = st.secrets.get("ACCESS_CODE", os.getenv("ACCESS_CODE", ""))
CODES_JSON = st.secrets.get("CODES_JSON", os.getenv("CODES_JSON", ""))
MIN_SECONDS_BETWEEN_CALLS = float(st.secrets.get("MIN_SECONDS_BETWEEN_CALLS", os.getenv("MIN_SECONDS_BETWEEN_CALLS", 3.0)))
DAILY_RESET = bool(int(st.secrets.get("DAILY_RESET", os.getenv("DAILY_RESET", "1"))))

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

INTRO_MD = """
### Case Overview (Read First)
You are consulting for a start-up ride-sharing company called Wisk, which operates a two-sided marketplace similar to ride-sharing platforms much like Lyft or Uber. 

The company just launched in a new city – Toledo, Ohio – and wants guidance on pricing. Specifically, they want to first focus on the pricing of their most popular route: from the airport to downtown (or vice versa). Currently, they charge riders \$25 per trip, and drivers earn \$19 for the trip.

The client has additional data, context, and clarifications, but will only provide it in response to thoughtful, targeted questions. Ask good questions to uncover the key information you will need.
"""

CASE_INFO = """
Context (Information also given to the students):
Wisk is a start-up ride-sharing company, which operates a two-sided marketplace similar to ride-sharing platforms much like Lyft or Uber. 

The company just launched in a new city – Toledo, Ohio – and wants guidance on pricing. Specifically, they want to first focus on the pricing of their most popular route: from the airport to downtown (or vice versa). Currently, they charge riders \$25 per trip, and drivers earn \$19 for the trip.

More context (Information not initially given to the students):
When Wisk launched at \$25 to rider, \$19 to driver, only about 60 of 100 ride requests found a driver. Wisk ran some experiments (details below) to help determine how changing the \$19 will likely affect the match rate.

Wisk also has estimated various cost parameters (details below) regarding the economics for drivers and riders.

Problem focus/Main decision:
Wisk wants to focus just on the decision of how much to pay the drivers for this trip (i.e., should it be more or less than \$19). They do not want to consider changes to the charge for riders (the \$25 per trip).

Objective:
Wisk wants to use the objective of trying to maximize the company’s net revenue (the difference between the amount
riders pay and the amount Lyft pays out to drivers) for this route (between the airport and downtown) in Toledo for the next 12 months.

Drivers:
- Customer acquisition cost (CAC) of a new driver is between \$400 - \$600. CAC is sensitive to the rate of acquisition since channels are only so deep.
- At the prevailing wage, drivers have a 5% monthly churn rate and complete 100 rides / month

Riders:
- CAC of a new rider is \$10 to \$20 (similar to driver CAC it’s sensitive to the rate of acquisition, since existing marketing channels are only so deep)
- Each rider requests about 1 ride per month on average.
- Riders who do not experience a failed to find driver event churn at 10 percent monthly.
- Riders who experience one or more failed to find driver events churn at 33 percent monthly.

Experiment:
In a 3-week experiment, reducing Wisk’s take from \$6 per ride to \$3 per ride increased the match rate from 60 percent to about 93 percent.
"""

SYSTEM_PROMPT = f"""
You are the client representative for Wisk, a ride-sharing startup launching a new market.
You are participating in a consulting simulation where students ask questions to gather
information and analyze the case.

Your role: provide information that exists in CASE_INFO when students ask
specific, relevant questions. You may also briefly confirm or correct a
student’s interpretation. You are NOT a coach or advisor.

Hard constraints (must follow):
- Do NOT recommend strategies, frameworks, or plans.
- Do NOT give step-by-step guidance or say “here’s how you should decide.”
- Do NOT synthesize or extrapolate beyond CASE_INFO.
- Do NOT reveal all information at once or on broad requests.
- Keep replies short and factual: 1–5 sentences or concise bullet points.
- If asked for recommendations or analysis (e.g., “what should I do,” “how should I set prices”),
  politely decline and prompt them to request specific facts instead.

Allowed behaviors:
- Answer direct, narrow questions with only the minimum relevant facts from CASE_INFO.
- Briefly confirm or correct a student’s interpretation of case facts.
- If a question is too broad, ask which variable or assumption they’d like clarified.

CASE_INFO (authoritative source starts below):
---
{CASE_INFO}
---
"""

DONT_DUMP_PATTERNS = [
    r"give (me|us) (all|everything)",
    r"what.*all.*information",
    r"dump.*info",
    r"provide.*full.*details",
    r"share.*entire.*case",
]

def looks_like_dump_request(text: str) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in DONT_DUMP_PATTERNS)

DB_PATH = "usage.db"
def db_init():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS usage (code TEXT, date TEXT, count INTEGER, PRIMARY KEY(code,date))")
    conn.commit(); conn.close()
def db_get_count(code: str, date: str) -> int:
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT count FROM usage WHERE code=? AND date=?", (code, date))
    row = cur.fetchone(); conn.close(); return row[0] if row else 0
def db_inc_count(code: str, date: str, inc: int = 1):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT count FROM usage WHERE code=? AND date=?", (code, date))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE usage SET count=? WHERE code=? AND date=?", (row[0] + inc, code, date))
    else:
        cur.execute("INSERT INTO usage (code, date, count) VALUES (?, ?, ?)", (code, date, inc))
    conn.commit(); conn.close()

def render_counters(remaining_session: int, max_requests: int, daily_remaining: int | None = None):
    used = max_requests - remaining_session
    pct = 0 if max_requests == 0 else int(100 * used / max_requests)
    if daily_remaining is not None:
        st.info(f"Prompts remaining (this session): {remaining_session} / {max_requests} | Daily remaining: {daily_remaining}")
    else:
        st.info(f"Prompts remaining (this session): {remaining_session} / {max_requests}")
    st.progress(pct, text=f"{remaining_session} of {max_requests} prompts remaining")

def call_openai_chat(messages: List[Dict[str, str]], model_name: str, temperature: float) -> str:
    if client is None:
        return "No OpenAI API key configured. Add OPENAI_API_KEY in Streamlit Secrets."
    sys = None; trimmed = []
    for m in messages:
        if m["role"] == "system":
            sys = m
        else:
            trimmed.append(m)
    trimmed = trimmed[-MAX_CONTEXT_MESSAGES:]
    convo = [sys] + trimmed if sys else trimmed
    resp = client.chat.completions.create(
        model=(model_name if model_name in ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"] else "gpt-4o-mini"),
        messages=convo,
        temperature=temperature
    )
    return resp.choices[0].message.content

def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)

def build_printable_html(title: str, messages: List[Dict[str, str]]) -> str:
    rows = []
    for m in messages:
        if m.get("role") == "system":
            continue
        role = "Student" if m.get("role") == "user" else "Client"
        content = normalize_text(m.get("content", "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows.append(f"<div class='msg {m.get('role')}'><div class='role'>{role}</div><div class='bubble'>{content}</div></div>")
    body = "\n".join(rows)
    styles = """
    <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    h1 { margin-bottom: 6px; }
    .sub { color: #555; margin-bottom: 18px; }
    .msg { margin: 10px 0; }
    .role { font-weight: bold; margin-bottom: 4px; }
    .bubble { background: #fafafa; border: 1px solid #ddd; border-radius: 8px; padding: 10px 12px; white-space: pre-wrap; }
    .user .bubble { background: #eef6ff; border-color: #cde3ff; }
    .assistant .bubble { background: #f8f8f8; }
    @media print {
      .no-print { display: none; }
      body { margin: 0.5in; }
    }
    </style>
    """
    date_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{title} Transcript</title>{styles}</head><body>"
    html += f"<h1>{title} – Conversation</h1><div class='sub'>Printed {date_str}</div>"
    html += body
    html += "<div class='no-print' style='margin-top:24px'><button onclick='window.print()'>Print</button></div>"
    html += "</body></html>"
    return html

st.set_page_config(page_title=APP_TITLE, layout="centered")
st.title(APP_TITLE)

codes = {}
if CODES_JSON:
    try:
        codes = json.loads(CODES_JSON)
        assert isinstance(codes, dict)
    except Exception:
        st.error("CODES_JSON is not valid JSON. Example: {\"ellie\": 40, \"nate\": 40}")
        st.stop()

per_student_mode = len(codes) > 0
if per_student_mode:
    entered = st.text_input("Enter your student code", type="password")
    if entered not in codes:
        st.info("This app requires a valid student code.")
        st.stop()
    db_init()
    today = dt.date.today().isoformat() if DAILY_RESET else "global"
    used = db_get_count(entered, today)
    per_student_quota = int(codes[entered])
    remaining_total = max(0, per_student_quota - used)
else:
    remaining_total = None
    if ACCESS_CODE_SECRET:
        ac = st.text_input("Enter access code", type="password")
        if ac != ACCESS_CODE_SECRET:
            st.info("This app requires an access code.")
            st.stop()

# Intro
st.markdown(INTRO_MD)

# Initialize state
if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}]
if "request_count" not in st.session_state:
    st.session_state["request_count"] = 0
if "last_time" not in st.session_state:
    st.session_state["last_time"] = 0.0

# Main controls (no sidebar)
col1, col2 = st.columns(2)
with col1:
    if st.button("Reset conversation", use_container_width=True):
        # Option A: full reset
        st.session_state.clear()
        st.rerun()
with col2:
    printable_html = build_printable_html(APP_TITLE, st.session_state["messages"])
    st.download_button(
        label="Download printable transcript (HTML)",
        data=printable_html,
        file_name="wisconsin_case_lab_transcript.html",
        mime="text/html",
        use_container_width=True
    )

# Chat input
disabled_input = (st.session_state["request_count"] >= MAX_REQUESTS) or (per_student_mode and remaining_total is not None and remaining_total <= 0)
user_text = st.chat_input("Ask your client a question...", disabled=disabled_input)

def call_and_append(user_text: str):
    st.session_state["messages"].append({"role": "user", "content": user_text})
    reply = call_openai_chat(st.session_state["messages"], MODEL_DEFAULT, TEMPERATURE_DEFAULT)
    st.session_state["messages"].append({"role": "assistant", "content": reply})
    st.session_state["request_count"] += 1
    st.session_state["last_time"] = time.time()

if user_text:
    now = time.time()
    if now - st.session_state["last_time"] < MIN_SECONDS_BETWEEN_CALLS:
        st.session_state["messages"].append({"role": "assistant", "content": "Please wait a few seconds between questions."})
    elif looks_like_dump_request(user_text):
        guard = "I cannot share everything at once. Try focusing on pricing, drivers, riders, or match rates."
        st.session_state["messages"].append({"role": "user", "content": user_text})
        st.session_state["messages"].append({"role": "assistant", "content": guard})
    elif st.session_state["request_count"] >= MAX_REQUESTS:
        st.session_state["messages"].append({"role": "assistant", "content": "You have reached your session limit. Use Reset conversation to start over."})
    elif per_student_mode and remaining_total is not None and remaining_total <= 0:
        st.session_state["messages"].append({"role": "assistant", "content": "You have reached your daily total. Please try again tomorrow or contact your instructor."})
    else:
        call_and_append(user_text)
        if per_student_mode and remaining_total is not None:
            db_inc_count(entered, today)

# Display history
for msg in st.session_state["messages"]:
    if msg["role"] == "system":
        continue
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.markdown(normalize_text(msg["content"]))

# Bottom counters only
remaining_session_bottom = max(0, MAX_REQUESTS - st.session_state["request_count"])
def render_counters_bottom():
    used = MAX_REQUESTS - remaining_session_bottom
    pct = 0 if MAX_REQUESTS == 0 else int(100 * used / MAX_REQUESTS)
    if per_student_mode and remaining_total is not None:
        st.info(f"Prompts remaining (this session): {remaining_session_bottom} / {MAX_REQUESTS} | Daily remaining: {remaining_total}")
    else:
        st.info(f"Prompts remaining (this session): {remaining_session_bottom} / {MAX_REQUESTS}")
    st.progress(pct, text=f"{remaining_session_bottom} of {MAX_REQUESTS} prompts remaining")

render_counters_bottom()

st.markdown("---")
st.caption("Tip: Be specific. Avoid asking for everything. Probe particular levers and metrics.")
