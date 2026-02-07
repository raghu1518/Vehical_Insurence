# Multilingual Multi-Agent Bot

Python CLI + REST API + WebSocket + HTML/CSS/JS UI for a multilingual, multi-agent chatbot. Default language is Hindi, and replies follow the user’s latest language. Includes common tools (time, calendar, greetings, sendoffs, FAQs), insurance claim flows, and support utilities.

## Features
- Multi-agent routing (language, intent, tools, flows, LLM).
- Configurable LLM backends: OpenAI, Groq, Ollama, Claude (plus mock).
- REST API + WebSocket + production-grade UI + CLI.
- System prompts managed in JSON and editable from UI.
- Automatic language detection for major Indian languages with same-language replies.
- Phone-number onboarding with Postgres policy lookup.
- Session isolation via `call_uuid` (also used as `session_id`).
- Accident, hospital, and roadside assistance flows with hospital/garage search.
- Roadside SMS via Telegram bot (chat_id mapped by phone number).
- FAQ RAG over PDFs.
- DB Admin UI + CRUD endpoints.
- Guardrails to block sensitive info (OTP/PIN/password/card data).
- JSONL transcripts and daily rotating logs in `logs/`.

## Quick Start

1. Create a virtual environment and install dependencies.

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure settings or environment variables.

`configs/settings.json` supports provider base URLs and API keys:

```json
{
  "default_language": "hi",
  "default_system_prompt_id": "core-multi",
  "llm": {
    "provider": "groq",
    "model": "llama-3.1-8b-instant",
    "base_url": "",
    "api_key": ""
  },
  "llm_base_urls": {
    "openai": "https://api.openai.com/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "ollama": "http://localhost:11434",
    "claude": "https://api.anthropic.com/v1/messages"
  },
  "postgres": {
    "user": "claim_user",
    "password": "claim_pass",
    "host": "192.168.13.235",
    "port": 5444,
    "db": "claim_db1"
  },
  "telegram": {
    "bot_token": "",
    "chat_id": ""
  }
}
```

Environment variables override settings.json:

```bash
set LLM_PROVIDER=openai
set LLM_MODEL=gpt-4o-mini
set OPENAI_API_KEY=YOUR_KEY
set GROQ_API_KEY=YOUR_KEY
set ANTHROPIC_API_KEY=YOUR_KEY
set LLM_BASE_URL=
set POSTGRES_USER=claim_user
set POSTGRES_PASSWORD=claim_pass
set POSTGRES_DB=claim_db1
set POSTGRES_HOST=192.168.13.235
set POSTGRES_PORT=5444
set TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT
set TELEGRAM_CHAT_ID=DEFAULT_CHAT_ID
```

3. Run the API.

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 9019
```

4. Open the UI at `http://localhost:9019`.

Phone number and call UUID are required for the chat API and UI.

## CLI

```bash
python cli.py
```

Commands:
- `/exit` quit
- `/reset` reset session
- `/lang en` switch language
- `/system` print system prompts

## API

### REST
- `POST /chat` requires:
  - `phone_number`
  - `call_uuid`
  - `message`
- `GET /system` / `POST /system` for system prompts
- `GET /config`

Sample:
```json
{
  "message": "I had an accident",
  "phone_number": "9999999999",
  "call_uuid": "a1b2c3d4",
  "system_prompt_id": "core-multi",
  "reset": false
}
```
Use the same `call_uuid` for the same conversation/session.

### WebSocket (Realtime)
- Connect to `ws://<host>:9019/ws`
- Send the same JSON payload as `/chat`
- Response:
  - `{ "type": "chat", ...ChatResponse }`
  - `{ "type": "error", "detail": ... }`

The UI uses WebSocket by default and falls back to REST if needed.

### DB Admin (no auth)
Use with care. Endpoints:
- `GET /db/tables`
- `GET /db/table/{table}/columns`
- `GET /db/table/{table}/rows?limit=&offset=`
- `POST /db/table/{table}/rows` `{ "data": {...} }`
- `PUT /db/table/{table}/rows` `{ "set": {...}, "where": {...} }`
- `DELETE /db/table/{table}/rows` `{ "where": {...} }`

## LLM Providers

Supported providers:
- `openai` (uses OpenAI-compatible chat completions)
- `groq` (OpenAI-compatible endpoint)
- `ollama` (local `http://localhost:11434/api/chat`)
- `claude` (Anthropic messages API)
- any other value uses a mock client

Environment variables:
- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLM_BASE_URL`
- `LLM_TIMEOUT`
- `OPENAI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`

## System Prompts

System prompts are stored in `configs/system_prompts.json` and exposed via `GET /system` and `POST /system`.

## Calendar Tool

Supported formats:
- English: `add event Team sync on 2026-02-06 at 10:30`
- Hindi: `कैलेंडर में इवेंट जोड़ो टीम सिंक 2026-02-06 समय 10:30`

List events:
- `list calendar`
- `कैलेंडर दिखाओ`

Remove events:
- `remove event Team sync`

## Claim Flow (Insurance Support)

Start:
- `/claim`
- `start claim flow`
- `क्लेम शुरू करो`

Cancel:
- `/cancel`
- `cancel claim`
- `क्लेम रद्द`

Flow fields (in order):
1. Policy number
2. Incident date (YYYY-MM-DD)
3. Location / Pincode
4. Damage type
5. Damage description
6. FIR filed? (interprets natural language)
7. FIR number (if yes)

## Hospital Flow
- If user asks for hospital/medical help, the bot asks for location or pincode first, then searches hospitals.

## Data Sources

Expected files:
- `data/hospitals.xlsx`
- `data/garages.xlsx`
- `data/faqs/*.pdf`

Update paths in `configs/settings.json` if needed.

## Logging & Transcripts

- Logs: `logs/app.log` (daily rotation)
- Transcripts: `logs/transcripts/YYYY-MM-DD/<call_uuid>.jsonl`

Each transcript line is JSON:
```json
{"timestamp":"2026-02-05T12:34:56.789+00:00","user_type":"user","message":"..."}
```

## Telegram SMS (Roadside)
Roadside SMS uses Telegram messages. Chat ID can be mapped by phone number in the `teligram` table (note spelling).

Example:
```sql
INSERT INTO teligram (phone_no, chat_id) VALUES ('9999999999', '123456789')
ON CONFLICT (phone_no) DO UPDATE SET chat_id = EXCLUDED.chat_id;
```

If no mapping exists, it falls back to `TELEGRAM_CHAT_ID` / settings.

## Files

- `app.py` API server
- `cli.py` CLI client
- `bot/` DDD package
  - `bot/application/` orchestration + flows
  - `bot/infrastructure/` DB, LLM, search, SMS, logging
  - `bot/shared/` i18n, tools, prompts, memory, guards
  - `bot/domain/` (reserved for domain entities/value objects)
- `static/` web UI
- `configs/` settings + system prompts
- `data/calendar.json` calendar storage
