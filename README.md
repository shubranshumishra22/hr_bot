# HR RAG + agent bot (prototype)

A LangChain agent that answers HR questions over Telegram. It routes between:
- **Structured lookups** (leave balance, leave history) → direct SQLite queries, standing in for a real HRMS API.
- **Policy questions** (carry-forward, WFH rules, maternity leave) → RAG over markdown policy docs via Chroma.
- **Actions** (apply for leave, raise a ticket) → writes to the mock DB with a `pending_manager_approval` status - nothing is auto-approved.

Built entirely on free tiers: Gemini 2.5 Flash or OpenRouter `:free` models for the LLM, local `sentence-transformers` for embeddings (no API cost), Chroma and SQLite running locally.

## Project layout

```
hr-bot-prototype/
├── config.py              # loads .env, picks LLM provider
├── db/
│   └── init_db.py         # mock HR database (employees, leave, tickets)
├── policies/               # markdown policy docs - edit/add freely
│   ├── leave_policy.md
│   └── wfh_policy.md
├── rag/
│   └── build_index.py      # builds the Chroma index from policies/
├── tools/
│   └── hr_tools.py          # tools the agent can call, bound per-employee
├── agent/
│   ├── llm.py                # swappable LLM factory (Gemini / OpenRouter)
│   └── agent_executor.py     # agent + memory, per employee session
└── bot/
    └── telegram_bot.py       # Telegram front-end (long polling)
```

## Setup

1. **Install dependencies** (Python 3.10+ recommended):
   ```
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```
   cp .env.example .env
   ```
   Then fill in:
   - `LLM_PROVIDER` — `gemini` or `openrouter`
   - `GOOGLE_API_KEY` — free key from https://aistudio.google.com/
   - `OPENROUTER_API_KEY` — free key from https://openrouter.ai/ (only needed if using OpenRouter)
   - `TELEGRAM_BOT_TOKEN` — create a bot by messaging **@BotFather** on Telegram and running `/newbot`

3. **Initialize the mock HR database**:
   ```
   python -m db.init_db
   ```
   This seeds 3 employees (ids 1, 2, 3) with leave balances.

4. **Build the policy RAG index** (first run downloads the free embedding model, ~90MB):
   ```
   python -m rag.build_index
   ```
   Re-run this any time you edit files in `policies/`.

5. **Start the bot**:
   ```
   python -m bot.telegram_bot
   ```

6. **Talk to it on Telegram**:
   - Send `/start`
   - Send `/register 1` (or 2, or 3) to link your Telegram account to a seeded employee
   - Try things like:
     - "How many leave days do I have left?"
     - "Can I carry forward unused earned leave to next year?"
     - "Book 2 days of casual leave from 2026-08-10 to 2026-08-11"
     - "My laptop screen is cracked"

## Known prototype shortcuts (fix before anything real)

- `/register` trusts whatever employee_id the user types — replace with OTP-to-work-email or SSO before this touches real data.
- Chat history is kept in memory and resets if the process restarts — fine for a demo, not for production.
- "Manager approval" is simulated as a status field — wire this to an actual notification (Slack/email/Telegram to the manager) before relying on it.
- Free-tier LLMs and embeddings are fine for a prototype but come with rate limits and, on some providers, training-data usage terms — don't route real employee PII through them.

## Extending it

- Add more tools in `tools/hr_tools.py` (e.g. `get_attendance`, `get_payslip_status`) following the same pattern — always bind them to `employee_id`, never let the LLM supply it.
- Add more policy docs to `policies/` and rebuild the index.
- Swap `create_tool_calling_agent` for a more explicit router chain if you want more control while learning LangChain internals.
