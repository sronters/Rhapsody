# Project Isolation

Rhapsody's main security boundary is the project/workspace.

Every meeting, document, task, decision, risk, memory chunk, and audit event is
stored with a workspace id. Telegram commands resolve the active workspace first,
then query or write only inside that workspace.

## Private Chats

- One Telegram user can have multiple projects.
- Private selected project mapping is per user.
- `/projects` lists only projects where the current Telegram user is a member.
- `/use_project` can select only a project visible to that user.
- `/ask` searches only the selected workspace.
- `/tasks`, `/decisions`, `/document`, and `/audit` are scoped to the selected
  workspace.

Same project names are allowed for different users if the users own different
workspaces. For example, User A can have `Alpha` and User B can also have
`Alpha`; memory does not merge by name.

## Group Chats

- Group selected project mapping is bound to the Telegram group chat.
- Group memory is saved only to the bound group project.
- A random non-manager cannot rebind an already-bound group.
- Rebinding/admin actions require owner/admin permission on the currently bound
  group project.

Current group member policy: Telegram group membership alone is not enough to
access memory. A Telegram user must also be a project member.

## Query Scope

The important query rule is simple: no command should search globally.

- `/ask` retrieves memory chunks filtered by `workspace_id`.
- `/tasks` lists tasks filtered by `workspace_id`.
- `/decisions` lists decisions filtered by `workspace_id`.
- `/audit` lists audit logs filtered by `workspace_id`.
- Document ingestion writes document metadata and memory chunks to the selected
  workspace.
- Meeting ingestion writes meeting, summary, tasks, decisions, risks, memory, and
  audit logs to the selected workspace.

## Verified

Verified in the current local flow:

- Private Alpha/Beta isolation with one user.
- Document isolation.
- Meeting memory isolation.
- Task isolation.
- Decision isolation.
- Audit isolation.
- Group project binding.
- Group memory does not leak private project data.
- Group hijack regression covered by automated test.
- Same-name private projects for different users covered by automated test.
- Second user cannot select another user's private project covered by automated
  test.

## Not Fully Manually Verified Yet

The following still require a real second Telegram identity:

- Real second Telegram user cross-user access test.
- Real second Telegram user group hijack attempt.

These should not be marked passed until a different Telegram account/session is
used. Testing with the same user does not prove cross-user isolation.
