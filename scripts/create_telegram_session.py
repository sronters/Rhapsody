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

        session = client.session.save()
    finally:
        client.disconnect()

    print("\nRECORDER_SESSION:")
    print(session)
    print("\nStore this value in listener_accounts.encrypted_session for a recorder account.")
    print("\nKeep this value private. It grants access to the Telegram recorder session.")


if __name__ == "__main__":
    main()
