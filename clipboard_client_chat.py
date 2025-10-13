# clipboard_client_chat.py
# Streamlit chatbot for Clipboard client case with access code and quota control
import os, re, time, json, sqlite3, datetime as dt
import streamlit as st
from typing import List, Dict
from openai import OpenAI

MODEL_DEFAULT = "gpt-4o-mini"
MAX_CONTEXT_MESSAGES = 30
TEMPERATURE_DEFAULT = 0.2
APP_TITLE = "📋 Clipboard Client Chat"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", st.secrets.get("OPENAI_API_KEY", ""))
ACCESS_CODE_SECRET = st.secrets.get("ACCESS_CODE", os.getenv("ACCESS_CODE", ""))
CODES_JSON = st.secrets.get("CODES_JSON", os.getenv("CODES_JSON", ""))
MAX_REQUESTS = int(st.secrets.get("MAX_REQUESTS", os.getenv("MAX_REQUESTS", 25)))
MIN_SECONDS_BETWEEN_CALLS = float(st.secrets.get("MIN_SECONDS_BETWEEN_CALLS", os.getenv("MIN_SECONDS_BETWEEN_CALLS", 3.0)))
DAILY_RESET = bool(int(st.secrets.get("DAILY_RESET", os.getenv("DAILY_RESET", "1"))))

client = OpenAI(api_key=OPENAI_API_KEY)

CASE_INFO = """Clipboard’s marketplace users “book a transaction in the future,” similar to Lyft’s ride scheduling.
Price = $25, Driver pay = $19, Match rate = 60%. Lowering Lyft’s take to $3 raised match rate to 93%.
Drivers: CAC $400–600, churn 5%, 100 rides/mo.
Riders: CAC $10–20, churn 10% if success, 33% if fail.
Goal: Maximize net revenue for next 12 months at $25 cap."""

SYSTEM_PROMPT = f"""You are a realistic product manager (the client) at Clipboard.
Reveal details only when students ask specific, relevant questions.
Never reveal all info or invent facts.
CASE_INFO:
{CASE_INFO}"""

INTRO_MD = """### 🧩 Case Overview
You are consulting for **Clipboard**, a marketplace like Lyft. The company is launching a new city and wants pricing guidance.
Ask targeted questions to uncover key data."""

DB_PATH = "usage.db"
def db_init():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS usage (code TEXT, date TEXT, count INTEGER, PRIMARY KEY(code,date))")
    conn.commit()
    conn.close()
def db_get_count(code, date):
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute("SELECT count FROM usage WHERE code=? AND date=?", (code, date))
    row = cur.fetchone(); conn.close(); return row[0] if row else 0
def db_inc_count(code, date):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO usage (code, date, count) VALUES (?, ?, COALESCE((SELECT count FROM usage WHERE code=? AND date=?),0)+1)", (code, date, code, date))
    conn.commit(); conn.close()

st.set_page_config(page_title=APP_TITLE, page_icon="📋", layout="centered")
st.title(APP_TITLE)
codes = {}
if CODES_JSON:
    try: codes = json.loads(CODES_JSON)
    except: st.error("Invalid CODES_JSON"); st.stop()
if codes:
    entered = st.text_input("Enter your student code:", type="password")
    if entered not in codes: st.stop()
    db_init(); today = dt.date.today().isoformat() if DAILY_RESET else "global"
    used = db_get_count(entered, today); quota = codes[entered]; remaining_total = max(0, quota - used)
else:
    if ACCESS_CODE_SECRET:
        code = st.text_input("Enter access code:", type="password")
        if code != ACCESS_CODE_SECRET: st.stop()

st.markdown(INTRO_MD)
if "messages" not in st.session_state: st.session_state["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}]
if "count" not in st.session_state: st.session_state["count"] = 0
if "last_time" not in st.session_state: st.session_state["last_time"] = 0.0

def call_openai_chat(messages):
    resp = client.chat.completions.create(model=MODEL_DEFAULT, messages=messages, temperature=TEMPERATURE_DEFAULT)
    return resp.choices[0].message.content

user_text = st.chat_input("Ask your client a question...")
if user_text:
    if time.time() - st.session_state["last_time"] < MIN_SECONDS_BETWEEN_CALLS:
        st.warning("Please wait a few seconds before the next question."); st.stop()
    if st.session_state["count"] >= MAX_REQUESTS:
        st.warning("Session limit reached."); st.stop()
    if codes and remaining_total <= 0:
        st.error("Daily quota reached. Try again tomorrow."); st.stop()
    st.session_state["messages"].append({"role": "user", "content": user_text})
    with st.spinner("Thinking..."):
        reply = call_openai_chat(st.session_state["messages"])
    st.session_state["messages"].append({"role": "assistant", "content": reply})
    st.session_state["count"] += 1; st.session_state["last_time"] = time.time()
    if codes: db_inc_count(entered, today)
    st.write(reply)
