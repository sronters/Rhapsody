from __future__ import annotations

import asyncio
import os
from getpass import getpass

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import ListenerAccount
from app.db.session import AsyncSessionFactory
from app.services.crypto import SecretCipher

try:
    from dotenv import load_dotenv
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient
except ImportError as exc:  # pragma: no cover - operator helper script
    raise SystemExit(
        "Missing dependencies. Install them with:\n"
        "python -m pip install -e .[listener-session]"
    ) from exc


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required in .env")
    return value


def encrypt_session(session_string: str) -> str:
    settings = get_settings()
    if settings.has_default_encryption_key:
        return session_string
    return SecretCipher(settings.encryption_key).encrypt(session_string)


def create_recorder_session() -> tuple[str, int, str | None, str]:
    api_id_raw = required_env("RHAPSODY_TELEGRAM_API_ID")
    api_hash = required_env("RHAPSODY_TELEGRAM_API_HASH")

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise SystemExit("RHAPSODY_TELEGRAM_API_ID must be a number.") from exc

    client = TelegramClient(StringSession(), api_id, api_hash)
    client.connect()
    try:
        if not client.is_user_authorized():
            method = input("Login method [qr/phone] (default: qr): ").strip().lower() or "qr"
            if method == "qr":
                qr_login = client.qr_login()
                print("\nScan this login URL with the Telegram mobile app:")
                print(qr_login.url)
                print("\nTelegram: Settings -> Devices -> Link Desktop Device.")
                try:
                    qr_login.wait(timeout=120)
                except SessionPasswordNeededError:
                    password = getpass("Telegram 2FA password: ")
                    client.sign_in(password=password)
            else:
                phone = input("Telegram phone number, for example +77011234567: ").strip()
                if not phone:
                    raise SystemExit("Telegram phone number is required.")
                client.send_code_request(phone)
                code = input("Telegram login code: ").strip()
                try:
                    client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    password = getpass("Telegram 2FA password: ")
                    client.sign_in(password=password)

        user = client.get_me()
        session_string = client.session.save()
        display_name = " ".join(
            part
            for part in [
                getattr(user, "first_name", None),
                getattr(user, "last_name", None),
            ]
            if part
        )
        return (
            session_string,
            int(user.id),
            getattr(user, "username", None),
            display_name or getattr(user, "username", None) or f"Recorder {user.id}",
        )
    finally:
        client.disconnect()


async def upsert_listener_account(
    *,
    telegram_user_id: int,
    username: str | None,
    display_name: str,
    encrypted_session: str,
) -> None:
    async with AsyncSessionFactory() as session:
        account = (
            await session.scalars(
                select(ListenerAccount).where(
                    ListenerAccount.telegram_user_id == telegram_user_id
                )
            )
        ).first()
        if account is None:
            account = ListenerAccount(
                telegram_user_id=telegram_user_id,
                username=username,
                display_name=display_name,
                encrypted_session=encrypted_session,
                status="AVAILABLE",
            )
            session.add(account)
            action = "created"
        else:
            account.username = username
            account.display_name = display_name
            account.encrypted_session = encrypted_session
            account.status = "AVAILABLE"
            account.current_call_session_id = None
            action = "updated"
        await session.commit()
    label = f"@{username}" if username else display_name
    print(f"listener_account={action} telegram_user_id={telegram_user_id} label={label}")


def main() -> None:
    load_dotenv()
    session_string, telegram_user_id, username, display_name = create_recorder_session()
    asyncio.run(
        upsert_listener_account(
            telegram_user_id=telegram_user_id,
            username=username,
            display_name=display_name,
            encrypted_session=encrypt_session(session_string),
        )
    )
    print("Recorder account is ready. Add it to the Telegram group before /listen.")


if __name__ == "__main__":
    main()
