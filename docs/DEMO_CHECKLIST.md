# Demo Checklist

This is a preparation checklist for a later demo. It does not mean the demo has
already passed.

## Before Demo

- `.env` is configured with no placeholder secrets.
- `TELEGRAM_BOT_TOKEN` is set.
- One LLM provider is configured, for example `AI_MODE=gemini` with
  `GEMINI_API_KEY`.
- Vision provider is configured if image understanding is shown.
- STT provider is configured if voice/audio is shown.
- `LISTENER_ENABLED=false` unless live-call listener is intentionally being
  tested separately.
- Docker stack is running.
- `curl http://localhost:8000/api/v1/health` returns `{"status":"ok",...}`.
- `curl http://localhost:8000/api/v1/ready` returns `{"status":"ready"}`.
- Bot logs do not show startup errors.
- Fresh DB is optional, but useful for a clean walkthrough.

## Private Demo

1. Open private chat with the bot.
2. Run `/start`.
3. Run `/new_project Alpha`.
4. Run `/meeting`.
5. Send:

   ```text
   In Alpha we decided to use Gemini. Baktiyar must test documents tomorrow.
   ```

6. Run `/ask What did we decide?`.
7. Run `/tasks`.
8. Run `/decisions`.
9. Run `/new_project Beta`.
10. Run `/ask What did we decide?` and confirm Alpha does not leak.
11. Run `/document`.
12. Add a Beta-only document.
13. Run `/ask` about the Beta document.
14. Run `/use_project Alpha`.
15. Run `/ask What did we decide?` and confirm Alpha memory returns.

## Group Demo

1. Create a Telegram test group.
2. Add the bot.
3. Run `/setup`.
4. Run `/new_project GroupProject` or `/use_project GroupProject`.
5. Run `/meeting`.
6. Send:

   ```text
   In GroupProject we decided to use Qdrant for vector search.
   ```

7. Run `/ask What did this group decide?`.
8. Run `/tasks`.
9. Run `/decisions`.
10. Run `/audit`.
11. Confirm group answers do not mention private Alpha/Beta memory.

## Security Checks Before Any Public Demo

- Use a real second Telegram identity for private cross-user access testing.
- Use a real second Telegram identity for group hijack testing.
- Confirm the group remains bound after rejected hijack attempts.
- Confirm `/ask` after the rejected hijack still answers from the original group
  project.
