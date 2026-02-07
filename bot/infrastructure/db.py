from __future__ import annotations

import logging
import re
import secrets
import string
import asyncio
from contextlib import contextmanager

from sqlalchemy import text, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .config import SETTINGS

log = logging.getLogger("db")
_CLAIM_ID_RE = re.compile(r"^[A-Z0-9]{7}$")
_TEXT_TYPES = {"text", "character varying", "character", "varchar"}


def db_url() -> str:
    pg = SETTINGS.postgres
    return (
        f"postgresql+psycopg://{pg.user}:{pg.password}"
        f"@{pg.host}:{pg.port}/{pg.db}"
    )


engine = create_engine(db_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _fetch_user_policies_sync(phone_no: str) -> dict:
    q = text(
        """
        SELECT
            policy_number,
            user_name,
            phone_number,
            vehicle_reg_number,
            vehicle_model,
            policy_type,
            rsa_covered,
            COALESCE(policy_status, 'ACTIVE') AS policy_status
        FROM policies
        WHERE phone_number = :phone
        ORDER BY policy_number DESC
        LIMIT 10
        """
    )
    try:
        with get_session() as s:
            rows = s.execute(q, {"phone": str(phone_no)}).mappings().all()
        policies = [dict(r) for r in rows]
        name = policies[0].get("user_name") if policies else None
        return {"name": name, "policies": policies}
    except Exception:
        log.exception("fetch_user_policies_failed", extra={"phone": phone_no})
        return {"name": None, "policies": []}

async def fetch_user_policies(phone_no: str) -> dict:
    return await asyncio.to_thread(_fetch_user_policies_sync, phone_no)


def _create_claim_sync(payload: dict) -> str:
    raw_claim_id = payload.get("claim_id")
    claim_id = None
    if raw_claim_id:
        cid = re.sub(r"\s+", "", str(raw_claim_id)).upper()
        if _CLAIM_ID_RE.fullmatch(cid):
            claim_id = cid

    def _generate_claim_id() -> str:
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(7))

    q = text(
        """
        INSERT INTO claims (
            claim_id, policy_number, phone_number, incident_date, location,
            damage_type, damages_desc, fir_filed, fir_no, status, created_at, updated_at
        )
        VALUES (
            :claim_id, :policy_number, :phone, :incident_date, :location,
            :damage_type, :damages_desc, :fir_filed, :fir_no, 'SUBMITTED', NOW(), NOW()
        )
        """
    )
    with get_session() as s:
        for _ in range(10):
            if not claim_id:
                claim_id = _generate_claim_id()
            try:
                s.execute(
                    q,
                    {
                        "claim_id": claim_id,
                        "policy_number": payload.get("policy_number"),
                        "phone": payload.get("phone_number"),
                        "incident_date": payload.get("incident_date"),
                        "location": payload.get("location"),
                        "damage_type": payload.get("damage_type"),
                        "damages_desc": payload.get("damage_description")
                        or payload.get("damages_desc"),
                        "fir_filed": bool(payload.get("fir_filed", False)),
                        "fir_no": payload.get("fir_no"),
                    },
                )
                s.commit()
                return claim_id
            except IntegrityError:
                s.rollback()
                claim_id = None
            except Exception:
                s.rollback()
                raise
    raise RuntimeError("unable to generate unique claim_id")

async def create_claim(payload: dict) -> str:
    return await asyncio.to_thread(_create_claim_sync, payload)


def _get_claim_status_sync(claim_id: str) -> dict:
    q = text(
        """
        SELECT claim_id, status, updated_at
        FROM claims
        WHERE claim_id = :cid
        LIMIT 1
        """
    )
    with get_session() as s:
        row = s.execute(q, {"cid": claim_id}).mappings().first()
    return dict(row) if row else {}

async def get_claim_status(claim_id: str) -> dict:
    return await asyncio.to_thread(_get_claim_status_sync, claim_id)


def _list_claims_sync(limit: int = 50) -> list[dict]:
    q1 = text(
        """
        SELECT claim_id, phone_number, policy_number, status, created_at, updated_at
        FROM claims
        ORDER BY created_at DESC
        LIMIT :lim
        """
    )
    q2 = text(
        """
        SELECT claim_id, phone_number, policy_number, status, created_at
        FROM claims
        ORDER BY created_at DESC
        LIMIT :lim
        """
    )
    with get_session() as s:
        try:
            rows = s.execute(q1, {"lim": int(limit)}).mappings().all()
            return [dict(r) for r in rows]
        except Exception:
            rows = s.execute(q2, {"lim": int(limit)}).mappings().all()
            return [dict(r) for r in rows]

async def list_claims(limit: int = 50) -> list[dict]:
    return await asyncio.to_thread(_list_claims_sync, limit)


def _list_rsa_allocations_sync(limit: int = 50) -> list[dict]:
    q = text(
        """
        SELECT id, phone_number, policy_id, status, created_at
        FROM rsa_allocations
        ORDER BY created_at DESC
        LIMIT :lim
        """
    )
    with get_session() as s:
        try:
            rows = s.execute(q, {"lim": int(limit)}).mappings().all()
            return [dict(r) for r in rows]
        except Exception:
            return []

async def list_rsa_allocations(limit: int = 50) -> list[dict]:
    return await asyncio.to_thread(_list_rsa_allocations_sync, limit)


def _save_chat_summary_sync(phone_no: str, call_uuid: str, summary_text: str) -> None:
    q = text(
        """
        INSERT INTO chat_summaries (phone_number, call_uuid, summary_text, created_at)
        VALUES (:phone, :call_uuid, :summary, NOW())
        """
    )
    with get_session() as s:
        s.execute(
            q,
            {
                "phone": str(phone_no),
                "call_uuid": call_uuid,
                "summary": summary_text,
            },
        )
        s.commit()


async def save_chat_summary(phone_no: str, call_uuid: str, summary_text: str) -> None:
    await asyncio.to_thread(_save_chat_summary_sync, phone_no, call_uuid, summary_text)


def _fetch_latest_summary_sync(phone_no: str) -> dict:
    q = text(
        """
        SELECT summary_text, created_at, call_uuid
        FROM chat_summaries
        WHERE phone_number = :phone
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    try:
        with get_session() as s:
            row = s.execute(q, {"phone": str(phone_no)}).mappings().first()
        return dict(row) if row else {}
    except Exception:
        log.exception("fetch_latest_summary_failed", extra={"phone": phone_no})
        return {}


async def fetch_latest_summary(phone_no: str) -> dict:
    return await asyncio.to_thread(_fetch_latest_summary_sync, phone_no)


def ensure_schema() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS teligram (
                    phone_no TEXT PRIMARY KEY,
                    chat_id TEXT
                )
                """
            )
        )

        cols = conn.execute(
            text(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'teligram'
                """
            )
        ).all()
        col_types = {row[0]: row[1] for row in cols}

        if "phone_no" not in col_types:
            conn.execute(text("ALTER TABLE teligram ADD COLUMN phone_no TEXT"))
        if "chat_id" not in col_types:
            conn.execute(text("ALTER TABLE teligram ADD COLUMN chat_id TEXT"))

        for col_name in ("phone_no", "chat_id"):
            data_type = col_types.get(col_name)
            if data_type and data_type not in _TEXT_TYPES:
                conn.execute(
                    text(
                        f"ALTER TABLE teligram ALTER COLUMN {col_name} TYPE TEXT USING {col_name}::text"
                    )
                )


def _get_telegram_chat_id_sync(phone_no: str) -> str | None:
    q = text(
        """
        SELECT chat_id
        FROM teligram
        WHERE phone_no = :phone
        LIMIT 1
        """
    )
    with get_session() as s:
        row = s.execute(q, {"phone": str(phone_no)}).mappings().first()
    return str(row["chat_id"]) if row and row.get("chat_id") is not None else None


async def get_telegram_chat_id(phone_no: str) -> str | None:
    return await asyncio.to_thread(_get_telegram_chat_id_sync, phone_no)


def get_telegram_chat_id_sync(phone_no: str) -> str | None:
    return _get_telegram_chat_id_sync(phone_no)


def _upsert_telegram_chat_id_sync(phone_no: str, chat_id: str) -> None:
    q = text(
        """
        INSERT INTO teligram (phone_no, chat_id)
        VALUES (:phone, :chat_id)
        ON CONFLICT (phone_no)
        DO UPDATE SET chat_id = EXCLUDED.chat_id
        """
    )
    with get_session() as s:
        s.execute(q, {"phone": str(phone_no), "chat_id": str(chat_id)})
        s.commit()


async def upsert_telegram_chat_id(phone_no: str, chat_id: str) -> None:
    await asyncio.to_thread(_upsert_telegram_chat_id_sync, phone_no, chat_id)
