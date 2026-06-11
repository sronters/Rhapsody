from __future__ import annotations

import inspect

from app.api.routes.memory import ask_memory
from app.api.routes.provider_keys import list_provider_keys


def test_memory_route_requires_actor_user_id_for_rbac() -> None:
    assert "actor_user_id" in inspect.signature(ask_memory).parameters


def test_provider_key_listing_requires_workspace_actor_context() -> None:
    signature = inspect.signature(list_provider_keys)

    assert "workspace_id" in signature.parameters
    assert "actor_user_id" in signature.parameters