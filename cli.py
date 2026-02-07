from __future__ import annotations

import asyncio
import json
import uuid

from bot.application.orchestrator import Orchestrator
from bot.infrastructure.config import SETTINGS
from bot.shared.i18n import LANGUAGE_NAMES, normalize_language
from bot.infrastructure.logging_setup import setup_logging
from bot.shared.memory import SessionStore
from bot.shared.system_prompts import load_system_prompts


async def main() -> None:
    settings = SETTINGS
    prompts = load_system_prompts()
    store = SessionStore(
        settings.default_language,
        settings.default_system_prompt_id,
        expire_seconds=settings.session.expire_minutes * 60,
    )
    orchestrator = Orchestrator(settings)

    setup_logging("cli")

    phone_number = ""
    while not phone_number:
        phone_number = input("Phone number (required): ").strip()

    call_uuid = input("Call UUID (leave blank to auto-generate): ").strip()
    if not call_uuid:
        call_uuid = str(uuid.uuid4())
        print(f"Generated Call UUID: {call_uuid}")

    session = store.get(call_uuid, phone_number)

    print("Multilingual Multi-Agent Bot (CLI)")
    print("Type /exit to quit, /reset to clear session, /lang <code> to switch language.")

    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye")
            break

        if not message:
            continue
        if message.startswith("/exit"):
            print("Bye")
            break
        if message.startswith("/reset"):
            session = store.reset(session.session_id)
            session.phone_number = phone_number
            session.call_uuid = call_uuid
            print("Session reset.")
            continue
        if message.startswith("/system"):
            print(json.dumps(prompts, ensure_ascii=False, indent=2))
            continue
        if message.startswith("/lang"):
            parts = message.split()
            if len(parts) > 1:
                candidate = normalize_language(parts[1])
                session.language = candidate if candidate in LANGUAGE_NAMES else candidate
                print(f"Language set to {session.language}")
            continue

        result = await orchestrator.handle(
            message=message,
            session=session,
            prompts=prompts,
        )

        session.language = result.language
        session.flow = result.flow_state
        session.history.append({"role": "user", "content": message})
        session.history.append({"role": "assistant", "content": result.reply})

        print(f"Bot: {result.reply}")


if __name__ == "__main__":
    asyncio.run(main())
