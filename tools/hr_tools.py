"""HR tools for the agent.

Important design choice: tools are built per-employee via `build_tools(employee_id)`.
The employee_id comes from your own auth/session logic (see bot/telegram_bot.py),
NEVER from something the LLM decides on its own. This mirrors the real-world
requirement that an employee can only ever see their own leave/attendance data -
the model is not trusted to enforce that boundary, the code is.
"""
import os
import sqlite3
from datetime import datetime, date

from langchain.tools import tool

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import HR_DB_PATH, CHROMA_DIR, DATABASE_URL, TELEGRAM_BOT_TOKEN

_retriever = None  # lazy-loaded singleton, shared across all employees


def _get_retriever():
    """Loads the persisted Chroma policy index once and reuses it."""
    global _retriever
    if _retriever is None:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from langchain_chroma import Chroma

        embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        vectorstore = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=embeddings,
            collection_name="hr_policies",
        )
        _retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
    return _retriever


def db_execute(query: str, params: tuple = ()) -> list:
    """Executes a query and returns fetched rows (if any). Handles SQLite/PostgreSQL dynamically."""
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        # Convert SQLite ? placeholder to Postgres %s
        query = query.replace("?", "%s")
        cursor = conn.cursor()
        cursor.execute(query, params)
        try:
            rows = cursor.fetchall()
        except Exception:
            rows = []
        conn.commit()
        conn.close()
        return rows
    else:
        conn = sqlite3.connect(HR_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(query, params)
        try:
            rows = cursor.fetchall()
        except Exception:
            rows = []
        conn.commit()
        conn.close()
        return rows


def send_manager_approval_request(
    manager_telegram_id: str,
    request_id: int,
    employee_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: float
):
    """Sends a Telegram message to the manager with Approve/Reject inline buttons."""
    import httpx
    if not TELEGRAM_BOT_TOKEN:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    text = (
        f"📋 *New Leave Request*\n\n"
        f"👤 *Employee:* {employee_name}\n"
        f"🌴 *Type:* {leave_type.replace('_', ' ').title()}\n"
        f"📅 *Dates:* {start_date} to {end_date} ({days} day(s))\n\n"
        f"Do you approve or reject this request?"
    )
    
    payload = {
        "chat_id": manager_telegram_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Approve ✅", "callback_data": f"approve_leave_{request_id}"},
                    {"text": "Reject ❌", "callback_data": f"reject_leave_{request_id}"}
                ]
            ]
        }
    }
    
    try:
        response = httpx.post(url, json=payload, timeout=10.0)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send manager approval Telegram notification: {e}")


def build_tools(employee_id: int):
    """Returns the list of LangChain tools, all bound to this one employee_id."""

    @tool
    def get_leave_balance() -> str:
        """Look up the current employee's leave balances by type
        (earned leave, sick leave, casual leave). Use this for any question
        about how many leave days someone has left. Takes no arguments."""
        rows = db_execute(
            "SELECT leave_type, balance FROM leave_balances WHERE employee_id = ?",
            (employee_id,),
        )
        if not rows:
            return "No leave balance records found for this employee."
        lines = [f"- {leave_type.replace('_', ' ').title()}: {balance} days" for leave_type, balance in rows]
        return "Current leave balances:\n" + "\n".join(lines)

    @tool
    def get_leave_history() -> str:
        """Look up the current employee's past and pending leave requests.
        Use this for questions like 'what leave have I taken' or 'is my
        leave request approved'. Takes no arguments."""
        rows = db_execute(
            "SELECT leave_type, start_date, end_date, days, status FROM leave_requests "
            "WHERE employee_id = ? ORDER BY requested_at DESC LIMIT 10",
            (employee_id,),
        )
        if not rows:
            return "No leave requests found."
        lines = [f"- {lt} from {sd} to {ed} ({d} days): {status}" for lt, sd, ed, d, status in rows]
        return "Recent leave requests:\n" + "\n".join(lines)

    @tool
    def apply_leave(leave_type: str, start_date: str, end_date: str, days: float) -> str:
        """Submit a leave application for the current employee. leave_type must
        be one of: earned_leave, sick_leave, casual_leave. start_date and
        end_date must be in YYYY-MM-DD format. days is the number of leave
        days being requested. This checks the employee's balance first and
        will refuse if there isn't enough leave available. Successful
        requests are created with status 'pending_manager_approval' - they
        are NOT auto-approved."""
        rows = db_execute(
            "SELECT balance FROM leave_balances WHERE employee_id = ? AND leave_type = ?",
            (employee_id, leave_type),
        )
        if not rows:
            return f"Unknown leave type '{leave_type}'. Valid types: earned_leave, sick_leave, casual_leave."
        balance = rows[0][0]
        if days > balance:
            return (
                f"Cannot submit: requested {days} days of {leave_type}, "
                f"but only {balance} days are available."
            )
        
        # Insert request
        db_execute(
            "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days, status, requested_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending_manager_approval', ?)",
            (employee_id, leave_type, start_date, end_date, days, datetime.now().isoformat()),
        )

        # Retrieve request ID and manager ID for notification flow
        req_rows = db_execute(
            "SELECT id FROM leave_requests WHERE employee_id = ? ORDER BY requested_at DESC LIMIT 1",
            (employee_id,)
        )
        request_id = req_rows[0][0] if req_rows else None

        emp_rows = db_execute("SELECT name, manager_id FROM employees WHERE id = ?", (employee_id,))
        if emp_rows:
            employee_name, manager_id = emp_rows[0]
            if manager_id:
                mgr_rows = db_execute("SELECT telegram_id FROM employees WHERE id = ?", (manager_id,))
                if mgr_rows and mgr_rows[0][0]:
                    manager_telegram_id = mgr_rows[0][0]
                    send_manager_approval_request(
                        manager_telegram_id,
                        request_id,
                        employee_name,
                        leave_type,
                        start_date,
                        end_date,
                        days
                    )

        return (
            f"Leave request submitted: {days} day(s) of {leave_type.replace('_', ' ')} "
            f"from {start_date} to {end_date}. Status: pending manager approval."
        )

    @tool
    def raise_ticket(category: str, description: str) -> str:
        """Raise an HR or IT helpdesk ticket on behalf of the current employee.
        category should be a short label like 'IT', 'Facilities', 'Payroll',
        or 'HR-general'. Use this for requests that aren't leave/attendance
        questions, e.g. 'my laptop is broken' or 'I need a visitor pass'."""
        db_execute(
            "INSERT INTO tickets (employee_id, category, description, status, created_at) "
            "VALUES (?, ?, ?, 'open', ?)",
            (employee_id, category, description, datetime.now().isoformat()),
        )
        return f"Ticket raised under '{category}'. HR/IT will follow up."

    @tool
    def search_hr_policy(query: str) -> str:
        """Search the company's HR policy documents (leave policy, WFH policy,
        handbook) for an answer to a policy question - e.g. carry-forward
        rules, WFH eligibility, maternity leave duration. Use this instead of
        guessing when the question is about a rule rather than a personal
        number."""
        retriever = _get_retriever()
        results = retriever.invoke(query)
        if not results:
            return "No relevant policy text found. Recommend escalating to HR directly."
        chunks = []
        for r in results:
            source = r.metadata.get("source", "policy document")
            chunks.append(f"[{source}]: {r.page_content.strip()}")
        return "\n\n".join(chunks)

    return [
        get_leave_balance,
        get_leave_history,
        apply_leave,
        raise_ticket,
        search_hr_policy,
    ]
