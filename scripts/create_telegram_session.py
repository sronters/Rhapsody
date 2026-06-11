from __future__ import annotations

import os
from getpass import getpass

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


def main() -> None:
    load_dotenv()

    api_id_raw = required_env("TELEGRAM_API_ID")
    api_hash = required_env("TELEGRAM_API_HASH")

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise SystemExit("TELEGRAM_API_ID must be a number.") from exc

    phone = input("Telegram phone number, for example +77011234567: ").strip()
    if not phone:
        raise SystemExit("Telegram phone number is required.")

    client = TelegramClient(StringSession(), api_id, api_hash)
    client.connect()
    try:
        if not client.is_user_authorized():
            client.send_code_request(phone)
            code = input("Telegram login code: ").strip()

            try:
                client.sign_in(phone, code)
            except SessionPasswordNeededError:
                password = getpass("Telegram 2FA password: ")
                client.sign_in(password=password)

        session = client.session.save()
    finally:
        client.disconnect()

    print("\nTELEGRAM_USER_SESSION:")
    print(session)
    print("\nCopy this value into your .env as:")
    print(f"TELEGRAM_USER_SESSION={session}")
    print("\nKeep this value private. It grants access to the Telegram user session.")


if __name__ == "__main__":
    main()
