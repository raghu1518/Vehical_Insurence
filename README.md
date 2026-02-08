# Vehicle Bot

Multilingual, multi-agent insurance support bot with:
- REST + WebSocket API
- Browser UI + CLI
- LLM-routed tools and stateful flows
- Postgres-backed onboarding + claims
- Excel-based hospital/garage search
- Guardrails for scope control and prompt protection

Default runtime language is from `configs/settings.json` (`default_language`), and the bot keeps conversation language per session.

## What This Bot Handles
- Onboarding and policy selection from caller phone number.
- Accident triage, medical/hospital guidance, roadside assistance.
- Claim submission flow (with incident date validation and FIR capture).
- Claim payment ETA questions.
- Calendar add/list/remove helpers.
- FAQ answers from PDF RAG.

Out-of-scope requests are blocked with a controlled scope message.

## Quick Start

1. Create virtual environment and install dependencies.

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure `configs/settings.json` and/or environment variables.

3. Run API server.

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 9019
```

4. Open UI.

`http://localhost:9019`

## Runtime Pipeline

For every incoming message (`/chat` or `/ws`):

1. Session lookup by `call_uuid` (`SessionStore`).
2. Language detection (`LanguageAgent`).
3. Prompt-disclosure input guardrail check.
4. Flow handling (`FlowAgent`) if active flow exists or flow start is detected.
5. If no flow outcome:
- intent classification (`IntentAgent`)
- tool execution (`ToolAgent`) for tool intents
- FAQ RAG fallback for `chat`/`faq`
- otherwise scope guardrail response.
6. Output guardrails (`apply_guardrails`) before returning reply.
7. Transcript append + structured logging.

## Agents (Detailed)

Implementation file: `bot/application/orchestrator.py`

| Agent | Purpose | Input | Output |
|---|---|---|---|
| `LanguageAgent` | Detects conversation language | message + current/default language | normalized language code |
| `IntentAgent` | Classifies top-level intent | message + language | one label from configured intent set |
| `ToolAgent` | Maps intent to tool function | intent + message + language | `ToolResult` or `None` |
| `ChatAgent` | Generic LLM reply generator | messages + system prompt | plain text reply |
| `YesNoAgent` | Semantic yes/no classifier for critical flow steps | message + context | `True`, `False`, or `None` |
| `StepResponseAgent` | Checks if message answers current flow prompt | message + prompt | `True`, `False`, or `None` |
| `LocationAgent` | Extracts location/pincode from user message | message + language | location text or `None` |
| `DateTimeAgent` | LLM-based datetime parser fallback | message + language + reference `now` | `ParsedDateTime` or `None` |
| `FaqAgent` | Retrieves best FAQ chunk via RAG | message + language | answer text or `None` |
| `FlowStartAgent` | Classifies which flow should start | message + language | `accident/hospital/roadside/claim/none` |
| `CustomerTypeAgent` | In unregistered flow, classifies `new` vs `existing` | message + language | `new/existing/unknown` |
| `BuyPolicyAgent` | Detects buy-policy intent for new customers | message + language | `True/False/None` |
| `Orchestrator` | Wires all agents and enforces final routing | request context | `AgentResult` |

## Tools (Detailed)

Implementation file: `bot/shared/tools.py`

| Tool function | Tool name | Used for | Behavior |
|---|---|---|---|
| `tool_time` | `time` | current time/date queries | Returns localized time string in configured timezone |
| `tool_greeting` | `greeting` | greetings | Localized greeting |
| `tool_sendoff` | `sendoff` | goodbye/no-more-help | Localized sendoff |
| `tool_claim_payment` | `claim_payment` | claim payment ETA | Returns fixed SLA message (4-7 working days) |
| `tool_faq` | `faq` | keyword FAQ fallback | i18n FAQ mapping |
| `tool_hospital_search` | `hospital_search` | hospital lookup | Finds nearest match via Excel search |
| `tool_garage_search` | `garage_search` | garage lookup | Finds nearest garage match |
| `tool_sms` | `sms` | SMS/Telegram notifications | Sends SMS via infrastructure adapter |
| `tool_calendar_add` | `calendar_add` | calendar add | Writes to `data/calendar.json` |
| `tool_calendar_list` | `calendar_list` | calendar list | Reads events from `data/calendar.json` |
| `tool_calendar_remove` | `calendar_remove` | calendar remove | Removes matching title entries |

Helper parsers in same file:
- `parse_add_event`
- `parse_remove_event`

## Flows (Detailed)

Primary flow engine: `bot/application/flows.py` (`FlowAgent`)

### Onboarding Flow (`OnboardingFlow`)

Start behavior:
- Loads profile by caller phone using Postgres.
- If one policy: auto-select and continue.
- If multiple policies: asks user to select policy.
- If no policy: diverts to unregistered flow.

Selection behavior:
- Accepts list index and normalized identifiers (policy number, registration, last digits) via `extract_policy_choice`.

### Unregistered Flow (`_handle_unregistered`)

Steps:
1. `customer_type` (`new` or `existing`)
2. `existing_phone` (for existing customer path)
3. `otp_verify` (OTP validation, TTL and max attempts)
4. `new_help` (new-customer request handling)

Behavior:
- `sms_enabled=false` uses fixed OTP `123456`.
- Existing customer path re-loads profile and re-enters onboarding.
- New customer cannot start claim flow; buy-policy requests trigger sales callback response.

### Accident Flow (`AccidentFlow`)

State machine:
1. `safe`
2. `medical`
3. `hospital_location` (if medical needed)
4. `drivable`
5. `rsa_consent` (if not drivable)
6. `rsa_location` (if RSA consent yes)
7. `claim_consent`

Behavior:
- Hospital lookup can run inside accident flow and then resumes remaining steps.
- RSA branch picks eligible vs paid wording based on selected policy.
- On claim consent yes, hands off to `ClaimFlow.start`.

### Hospital Flow (`HospitalFlow`)

State machine:
1. `location`

Behavior:
- Validates pincode format.
- Searches hospitals via Excel index.
- Sends optional SMS with hospital details.
- Supports follow-up "other hospital" pattern and avoids same previous result when alternatives exist.

### Roadside Flow (`RoadsideFlow`)

State machine:
1. `vehicle` (optional if vehicle already known)
2. `location`

Behavior:
- Validates pincode.
- Searches garage provider and sends SMS.
- Completes with roadside follow-up prompt.

### Claim Flow (`ClaimFlow`)

State machine:
1. `policy` (if not already selected)
2. `incident_date`
3. `location`
4. `damage_type`
5. `description`
6. `fir_filed`
7. `fir_no` (conditional)
8. submit

Date parsing behavior:
- First tries deterministic parser (`parse_natural_datetime`) in `bot/shared/datetime_parser.py`.
- Falls back to `DateTimeAgent` LLM parse when deterministic parsing fails.
- Rejects future incident dates by configured timezone (`SETTINGS.timezone`).

Other validations:
- Invalid pincode detection for claim location.
- Cancellation via `/cancel` and other cancel hints.

### Flow Detours and Resumption (`FlowAgent`)

`FlowAgent` supports in-flow detours with prompt resumption:
- Hospital detour while another flow is active.
- Roadside/claim detours with current-step prompt restored after detour.
- Critical yes/no steps are protected from accidental sendoff/interrupt.
- Location steps accept explicit pincode and free-text locality fallback.

## Guardrails

Implementation file: `bot/shared/guardrails.py`

Input guardrails:
- Blocks prompt-disclosure and jailbreak-style requests.

Output guardrails:
- Blocks sensitive response content (OTP/PIN/password/card/CVV/bank-account).
- Blocks prompt/internal instruction leakage text.

Scope guardrail:
- If request is outside supported insurance assistant functionality and no valid tool/flow/RAG route applies, bot returns a constrained scope message.

## API Reference

### Core Endpoints
- `GET /`
- `GET /health`
- `GET /debug/runtime`
- `GET /config`
- `GET /system`
- `POST /system`
- `POST /chat`
- `WS /ws`

### Chat Request (`POST /chat`)

Required:
- `message`
- `phone_number`
- `call_uuid`

Optional:
- `language`
- `system_prompt_id`
- `reset`

Example:

```json
{
  "message": "I had an accident",
  "phone_number": "9999999999",
  "call_uuid": "a1b2c3d4",
  "system_prompt_id": "core-multi",
  "reset": false
}
```

Use the same `call_uuid` to continue the same session.

### WebSocket (`/ws`)

Connect:
- `ws://<host>:9019/ws`

Send:
- same JSON as `/chat`

Receive:
- `{ "type": "chat", ...ChatResponse }`
- `{ "type": "error", "detail": ... }`
- `{ "type": "pong" }` for ping payloads

## DB Admin Endpoints

No auth by default. Restrict at network/proxy level before production use.

- `GET /db/tables`
- `GET /db/table/{table}/columns`
- `GET /db/table/{table}/rows?limit=&offset=`
- `POST /db/table/{table}/rows` with `{ "data": {...} }`
- `PUT /db/table/{table}/rows` with `{ "set": {...}, "where": {...} }`
- `DELETE /db/table/{table}/rows` with `{ "where": {...} }`

## Configuration

Source file: `configs/settings.json`

Key sections:
- `default_language`, `default_system_prompt_id`, `timezone`
- `llm` and `llm_base_urls`
- `postgres`
- `data_paths`
- `logging`
- `telegram` (`sms_enabled` toggle)
- `session`

Environment variables override file settings (`LLM_PROVIDER`, `LLM_MODEL`, `POSTGRES_*`, `TELEGRAM_*`, `TIMEZONE`, and others in `bot/infrastructure/config.py`).

## Data Sources

Expected data files:
- `data/hospitals.xlsx`
- `data/garages.xlsx`
- `data/faqs/*.pdf`
- `data/calendar.json`

Search behavior:
- Hospital and garage search translates query to English before matching (`bot/infrastructure/search.py` + `bot/shared/translator.py`).

## Logging and Transcripts

- App logs: `logs/app.log` (rotating file handler).
- Transcripts: `logs/transcripts/YYYY-MM-DD/<call_uuid>.jsonl`

Transcript record example:

```json
{"timestamp":"2026-02-05T12:34:56.789+00:00","user_type":"user","message":"..."}
```

## CLI

Run:

```bash
python cli.py
```

Commands:
- `/exit`
- `/reset`
- `/lang en`
- `/system`

## Testing

Run:

```bash
pytest -q
```

Scenario tests are in `tests/test_scenarios.py`, including onboarding selection, claim validations, unregistered flow, and flow behavior regressions.

## Project Structure

- `app.py` FastAPI app and transport layer
- `cli.py` command-line client
- `bot/application/` orchestrator and flow engine
- `bot/infrastructure/` config, DB, LLM clients, search, SMS, logging
- `bot/shared/` i18n, guardrails, tools, memory, parser, prompts, transcript
- `static/` browser UI
- `configs/` settings and system prompts
- `data/` excel/pdf/calendar data
- `tests/` automated tests
