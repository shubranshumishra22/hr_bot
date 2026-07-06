"""Builds a LangChain tool-calling agent, scoped to one employee_id at a time.

Each Telegram user gets their own AgentExecutor + chat history, cached in
memory for the life of the process. For a prototype that's plenty; for
production you'd back the chat history with Redis or a DB.
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.hr_tools import build_tools
from agent.llm import get_llm
from config import HR_DB_PATH, DATABASE_URL

from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory

SYSTEM_PROMPT = """You are an HR assistant for company employees, reachable via Telegram.

Rules you must always follow:
1. For any question about a specific employee's leave balance, leave history,
   or attendance, use the tools provided - never guess or estimate a number.
2. For questions about policy rules (carry-forward, WFH eligibility, maternity
   leave, etc.), use the search_hr_policy tool and answer only from what it
   returns. If it returns nothing relevant, say so and suggest contacting HR.
3. To submit a leave request, use the apply_leave tool. Always confirm the
   leave type, dates, and number of days back to the employee before calling
   it if any of those were ambiguous.
4. If the message describes a grievance, harassment complaint, mental health
   concern, or anything involving conflict with a manager or colleague, do
   NOT try to resolve it yourself. Acknowledge it briefly, tell the employee
   you're flagging it for a human HR representative, and use the raise_ticket
   tool with category 'HR-sensitive' - do not ask probing follow-up questions.
5. Keep answers short and clear - this is a chat interface, not a document.
"""

def _get_session_history(session_id: str) -> SQLChatMessageHistory:
    conn_str = DATABASE_URL if DATABASE_URL else f"sqlite:///{HR_DB_PATH}"
    return SQLChatMessageHistory(
        session_id=session_id,
        connection_string=conn_str,
        table_name="message_store"
    )


def build_agent_for_employee(employee_id: int):
    llm = get_llm()
    tools = build_tools(employee_id)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

    agent_with_history = RunnableWithMessageHistory(
        executor,
        _get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
    )
    return agent_with_history


def ask(employee_id: int, message: str) -> str:
    """Convenience entry point used by the Telegram bot."""
    agent = build_agent_for_employee(employee_id)
    result = agent.invoke(
        {"input": message},
        config={"configurable": {"session_id": str(employee_id)}},
    )
    return result["output"]
