# Telegram Flow

Rhapsody is used mainly through Telegram. The bot stores team context by project
and answers from the selected project only.

## Private Chat Flow

Start with the bot in a private chat:

```text
/start
/new_project Alpha
```

Then add project context:

```text
/meeting
In Alpha we decided to use Gemini. Baktiyar must test documents tomorrow.
```

Ask from memory:

```text
/ask What did we decide?
```

Expected behavior: the answer should come from Alpha memory and include sources.

Add documents:

```text
/document
Beta document: The Beta project uses Postgres only.
```

List project work:

```text
/tasks
/decisions
/audit
```

Switch projects:

```text
/projects
/use_project Alpha
/use_project Beta
```

Private project selection is per Telegram user. If one user selects `Beta`, that
does not change another user's selected project.

## Group Chat Flow

1. Create a Telegram group.
2. Add the bot.
3. Run:

```text
/setup
```

In a group, `/setup` does not silently create a new project for every user. The
group needs an explicit project selection or creation:

```text
/new_project GroupProject
```

or:

```text
/use_project GroupProject
```

After the group is bound, group meeting and document memory is saved only to that
bound project:

```text
/meeting
In GroupProject we decided to use Qdrant for vector search.

/ask What did this group decide?
/tasks
/decisions
/audit
```

## If No Project Is Selected

Commands that need project context return a setup message instead of guessing:

```text
Сначала выберите проект: /projects или создайте новый: /new_project Название
```

The user should create a project or select one before sending meetings,
documents, or questions.

## Group Hijack Protection

An already-bound group cannot be rebound by a random non-manager. A user trying
to run `/new_project Evil` or `/use_project Evil` in a group must be an
owner/admin of the currently bound group project.

This protection is covered by automated regression tests. A real second-user
manual Telegram hijack test is still pending.

## Clean Error Cases

- Missing project: the bot asks the user to select or create a project.
- Missing STT: audio/voice/video returns a clean configuration error.
- Missing or failing LLM provider: the bot returns a clean provider error.
- Unsupported files: the bot returns an unsupported file type message.
