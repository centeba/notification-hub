"""Tests covering smart-llm integration:
- CurrentUserPayload.id alias
- settings.fernet_llm_key derivation
- AI agent config and skill Pydantic schemas
- /integrations/claude/complete route (new provider-based signature)
- /ai-agents/ CRUD routes (agent configs + LLM keys)
- /ai-skills/ CRUD routes
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Shared fixtures ───────────────────────────────────────────────────────────

COMPANY_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
SKILL_ID = uuid.uuid4()
AGENT_CONFIG_ID = uuid.uuid4()
LLM_KEY_ID = uuid.uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# 1. CurrentUserPayload.id alias
# ─────────────────────────────────────────────────────────────────────────────


class TestCurrentUserPayload:
    def test_id_aliases_user_id(self):
        """smart-llm routers access current_user.id — must equal user_id."""
        from integration_hub_backend.api.api.deps import CurrentUserPayload

        user = CurrentUserPayload(
            user_id=USER_ID,
            company_id=COMPANY_ID,
            role="company_admin",
            email="admin@example.com",
        )
        assert user.id == USER_ID
        assert user.id is user.user_id

    def test_id_works_for_platform_admin(self):
        from integration_hub_backend.api.api.deps import CurrentUserPayload

        user = CurrentUserPayload(
            user_id=USER_ID,
            company_id=None,
            role="platform_admin",
            email="platform@example.com",
        )
        assert user.id == USER_ID
        assert user.is_platform_admin


# ─────────────────────────────────────────────────────────────────────────────
# 2. Fernet key derivation
# ─────────────────────────────────────────────────────────────────────────────


class TestFernetKeyDerivation:
    def test_derived_key_is_valid_fernet_key(self):
        """fernet_llm_key must be 44-char URL-safe base64 encoding 32 bytes."""
        from integration_hub_backend.api.core.config import Settings

        s = Settings(SECRET_KEY="test-secret-key-for-unit-tests", LLM_ENCRYPTION_KEY="")
        key = s.fernet_llm_key

        raw = base64.urlsafe_b64decode(key + "==")
        assert len(raw) == 32, "Fernet key must encode exactly 32 bytes"

    def test_explicit_key_takes_precedence(self):
        """When LLM_ENCRYPTION_KEY is set it is returned unchanged."""
        from integration_hub_backend.api.core.config import Settings

        valid_key = base64.urlsafe_b64encode(b"a" * 32).decode()
        s = Settings(SECRET_KEY="anything", LLM_ENCRYPTION_KEY=valid_key)
        assert s.fernet_llm_key == valid_key

    def test_different_secret_keys_produce_different_fernet_keys(self):
        from integration_hub_backend.api.core.config import Settings

        s1 = Settings(SECRET_KEY="secret-one", LLM_ENCRYPTION_KEY="")
        s2 = Settings(SECRET_KEY="secret-two", LLM_ENCRYPTION_KEY="")
        assert s1.fernet_llm_key != s2.fernet_llm_key

    def test_same_secret_key_is_deterministic(self):
        from integration_hub_backend.api.core.config import Settings

        s1 = Settings(SECRET_KEY="stable-key", LLM_ENCRYPTION_KEY="")
        s2 = Settings(SECRET_KEY="stable-key", LLM_ENCRYPTION_KEY="")
        assert s1.fernet_llm_key == s2.fernet_llm_key


# ─────────────────────────────────────────────────────────────────────────────
# 3. Pydantic schema validation
# ─────────────────────────────────────────────────────────────────────────────


class TestSchemas:
    def test_ai_skill_create_defaults(self):
        from integration_hub_backend.api.models.ai_agent import AISkillCreate

        skill = AISkillCreate(name="pii-filter")
        assert skill.is_active is True
        assert skill.label is None
        assert skill.content is None

    def test_ai_skill_create_full(self):
        from integration_hub_backend.api.models.ai_agent import AISkillCreate

        skill = AISkillCreate(
            name="summarizer",
            label="Summarizer",
            description="Summarizes text",
            icon="document",
            content="Always return a JSON {summary: string}.",
            is_active=True,
        )
        assert skill.name == "summarizer"
        assert skill.content == "Always return a JSON {summary: string}."

    def test_ai_skill_update_all_optional(self):
        from integration_hub_backend.api.models.ai_agent import AISkillUpdate

        update = AISkillUpdate()
        assert update.model_dump(exclude_unset=True) == {}

    def test_ai_agent_config_create_defaults(self):
        from integration_hub_backend.api.models.ai_agent import AIAgentConfigCreate

        cfg = AIAgentConfigCreate(name="my-agent")
        assert cfg.provider_type == "anthropic"
        assert cfg.model_name == "claude-3-5-sonnet-20240620"
        assert cfg.is_active is True
        assert cfg.skill_ids == []

    def test_ai_agent_config_create_with_skills(self):
        from integration_hub_backend.api.models.ai_agent import AIAgentConfigCreate

        s1, s2 = uuid.uuid4(), uuid.uuid4()
        cfg = AIAgentConfigCreate(
            name="agent-with-skills",
            provider_type="openai",
            model_name="gpt-4o",
            skill_ids=[s1, s2],
        )
        assert cfg.provider_type == "openai"
        assert len(cfg.skill_ids) == 2

    def test_ai_agent_config_update_partial(self):
        from integration_hub_backend.api.models.ai_agent import AIAgentConfigUpdate

        update = AIAgentConfigUpdate(model_name="gpt-4o-mini")
        dumped = update.model_dump(exclude_unset=True)
        assert dumped == {"model_name": "gpt-4o-mini"}

    def test_company_llm_api_key_create(self):
        from integration_hub_backend.api.models.ai_agent import CompanyLLMApiKeyCreate

        key = CompanyLLMApiKeyCreate(provider="anthropic", api_key="sk-ant-xxx")
        assert key.provider == "anthropic"
        assert key.api_key == "sk-ant-xxx"

    def test_message_schema(self):
        from integration_hub_backend.api.models.ai_agent import Message

        m = Message(message="Agent config deleted")
        assert m.message == "Agent config deleted"

    def test_ai_skill_public_from_orm(self):
        """AISkillPublic must validate from a dict simulating ORM attribute access."""
        from integration_hub_backend.api.models.ai_agent import AISkillPublic

        now = datetime.now(UTC)
        pub = AISkillPublic.model_validate(
            {
                "id": SKILL_ID,
                "company_id": COMPANY_ID,
                "name": "test-skill",
                "label": None,
                "description": None,
                "icon": None,
                "content": "Do things.",
                "is_active": True,
                "created_at": now,
            }
        )
        assert pub.id == SKILL_ID
        assert pub.content == "Do things."

    def test_ai_agent_config_public_includes_skills(self):
        from integration_hub_backend.api.models.ai_agent import AIAgentConfigPublic, AISkillPublic

        now = datetime.now(UTC)
        skill = AISkillPublic(
            id=SKILL_ID,
            company_id=COMPANY_ID,
            name="helper",
            is_active=True,
            created_at=now,
        )
        cfg = AIAgentConfigPublic(
            id=AGENT_CONFIG_ID,
            company_id=COMPANY_ID,
            name="my-agent",
            provider_type="anthropic",
            model_name="claude-3-5-sonnet-20240620",
            is_active=True,
            created_at=now,
            skills=[skill],
        )
        assert len(cfg.skills) == 1
        assert cfg.skills[0].name == "helper"


# ─────────────────────────────────────────────────────────────────────────────
# 4. /integrations/claude/complete route
# ─────────────────────────────────────────────────────────────────────────────


def _make_claude_test_client():
    """Return a TestClient for the Claude router with auth and DB overridden."""
    from fastapi import FastAPI

    from integration_hub_backend.api.api.deps import (
        ApiKeyContext,
        get_api_key_context,
        get_db,
    )
    from integration_hub_backend.api.api.routes.integrations.claude import router

    app = FastAPI()
    app.include_router(router, prefix="/integrations")

    mock_ctx = ApiKeyContext(company_id=COMPANY_ID, scopes=["integrations:claude"])
    mock_session = AsyncMock()
    # The LLM budget gate (assert_llm_allowed -> _load_company_budget) reads the
    # company cap via (await session.execute(stmt)).scalars().first(). Default
    # execute to a sync result resolving to None (no cap) so the gate passes.
    _budget_result = MagicMock()
    _budget_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=_budget_result)

    async def _mock_db():
        yield mock_session

    app.dependency_overrides[get_api_key_context] = lambda: mock_ctx
    app.dependency_overrides[get_db] = _mock_db

    return TestClient(app), mock_session


class TestClaudeRoute:
    def test_complete_uses_smart_llm_key_store(self):
        """POST /integrations/claude/complete resolves key via smart-llm store."""
        from smart_llm.base import LLMResponse

        client, _ = _make_claude_test_client()

        mock_response = LLMResponse(
            data={"result": "42"},
            provider="anthropic",
            metadata={"model": "claude-3-5-sonnet-20240620"},
        )

        with (
            patch(
                "integration_hub_backend.api.services.ai_service.get_company_api_key",
                new_callable=AsyncMock,
            ) as mock_key,
            patch("integration_hub_backend.api.services.ai_service.Agent") as MockAgent,
        ):
            mock_key.return_value = "sk-ant-from-store"
            mock_instance = AsyncMock()
            mock_instance.analyze = AsyncMock(return_value=mock_response)
            MockAgent.return_value = mock_instance

            resp = client.post(
                "/integrations/claude/complete",
                json={"prompt": "What is 6 × 7?"},
                headers={"X-API-Key": "nhk_xxxxxxxx.secret"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == {"result": "42"}
        assert body["provider"] == "anthropic"

    def test_complete_with_explicit_openai_provider(self):
        """Route forwards the provider field to AIService correctly."""
        from smart_llm.base import LLMResponse

        client, _ = _make_claude_test_client()

        mock_response = LLMResponse(
            data={"answer": "yes"},
            provider="openai",
            metadata={"model": "gpt-4o"},
        )

        with (
            patch(
                "integration_hub_backend.api.services.ai_service.get_company_api_key",
                new_callable=AsyncMock,
            ) as mock_key,
            patch("integration_hub_backend.api.services.ai_service.Agent") as MockAgent,
        ):
            mock_key.return_value = "sk-openai-key"
            mock_instance = AsyncMock()
            mock_instance.analyze = AsyncMock(return_value=mock_response)
            MockAgent.return_value = mock_instance

            resp = client.post(
                "/integrations/claude/complete",
                json={"prompt": "Hello GPT", "provider": "openai", "model_name": "gpt-4o"},
                headers={"X-API-Key": "nhk_xxxxxxxx.secret"},
            )

        assert resp.status_code == 200
        assert resp.json()["provider"] == "openai"
        MockAgent.assert_called_once()
        _, kwargs = MockAgent.call_args
        assert kwargs["provider_type"] == "openai"
        assert kwargs["model_name"] == "gpt-4o"

    def test_complete_no_key_returns_400(self):
        """Route returns HTTP 400 when no key is available for the provider."""
        client, _ = _make_claude_test_client()

        with patch(
            "integration_hub_backend.api.services.ai_service.get_company_api_key",
            new_callable=AsyncMock,
        ) as mock_key:
            mock_key.return_value = None  # nothing in key store, no credential_id

            resp = client.post(
                "/integrations/claude/complete",
                json={"prompt": "Will this fail?"},
                headers={"X-API-Key": "nhk_xxxxxxxx.secret"},
            )

        assert resp.status_code == 400
        assert "No LLM API key found" in resp.json()["detail"]

    def test_complete_credential_id_optional(self):
        """credential_id is no longer required; omitting it must not cause a 422."""
        from smart_llm.base import LLMResponse

        client, _ = _make_claude_test_client()

        mock_response = LLMResponse(
            data={},
            provider="anthropic",
            metadata={"model": "claude-3-5-sonnet-20240620"},
        )

        with (
            patch(
                "integration_hub_backend.api.services.ai_service.get_company_api_key",
                new_callable=AsyncMock,
            ) as mock_key,
            patch("integration_hub_backend.api.services.ai_service.Agent") as MockAgent,
        ):
            mock_key.return_value = "sk-ant-key"
            mock_instance = AsyncMock()
            mock_instance.analyze = AsyncMock(return_value=mock_response)
            MockAgent.return_value = mock_instance

            resp = client.post(
                "/integrations/claude/complete",
                # No credential_id field — must be accepted
                json={"prompt": "test"},
                headers={"X-API-Key": "nhk_xxxxxxxx.secret"},
            )

        assert resp.status_code == 200

    def test_scope_enforcement(self):
        """Route rejects API keys missing the integrations:claude scope."""
        from fastapi import FastAPI

        from integration_hub_backend.api.api.deps import ApiKeyContext, get_api_key_context, get_db
        from integration_hub_backend.api.api.routes.integrations.claude import router

        app = FastAPI()
        app.include_router(router, prefix="/integrations")

        # Scope deliberately missing "integrations:claude"
        wrong_scope_ctx = ApiKeyContext(company_id=COMPANY_ID, scopes=["integrations:gmail"])
        app.dependency_overrides[get_api_key_context] = lambda: wrong_scope_ctx
        app.dependency_overrides[get_db] = lambda: AsyncMock()

        c = TestClient(app)
        resp = c.post(
            "/integrations/claude/complete",
            json={"prompt": "test"},
            headers={"X-API-Key": "nhk_xxxxxxxx.secret"},
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 5. /ai-agents/ CRUD routes (agent configs + LLM keys)
# ─────────────────────────────────────────────────────────────────────────────


def _make_agents_router(get_key_store_fn=None, *, with_sync: bool = False):
    """Build the smart-llm agents router from the factory (no HTTP client).

    Pass ``get_key_store_fn`` to inject a mock key-store factory for tests
    that exercise LLM key management endpoints.  The factory closes over this
    reference directly, so module-level patching does not work — the mock must
    be injected here at construction time.

    Pass ``with_sync=True`` to register the optional ``POST /ai-agents/sync``
    endpoint used by vertical-app AgentBundle.register_with().
    """
    from smart_llm.api.llm_service import get_key_store
    from smart_llm.api.routers.agents import create_agents_router

    from integration_hub_backend.api.api.deps import (
        CompanyAdminDep,
        CurrentUser,
        InternalServiceDep,
        SessionDep,
    )
    from integration_hub_backend.api.core.audit import log_audit
    from integration_hub_backend.api.models.ai_agent import (
        AIAgentConfig,
        AIAgentConfigCreate,
        AIAgentConfigPublic,
        AIAgentConfigsPublic,
        AIAgentConfigUpdate,
        AIAgentSkillLink,
        AIAgentSyncRequest,
        AIAgentSyncResponse,
        AIAgentSyncResultItem,
        AISkill,
        AISkillPublic,
        CompanyLLMApiKeyCreate,
        CompanyLLMApiKeyPublic,
        CompanyLLMApiKeysPublic,
        Message,
    )

    kwargs = dict(
        SessionDep=SessionDep,
        CurrentUser=CurrentUser,
        CompanyAdminDep=CompanyAdminDep,
        AIAgentConfig=AIAgentConfig,
        AISkill=AISkill,
        AISkillPublic=AISkillPublic,
        AIAgentSkillLink=AIAgentSkillLink,
        AIAgentConfigPublic=AIAgentConfigPublic,
        AIAgentConfigCreate=AIAgentConfigCreate,
        AIAgentConfigUpdate=AIAgentConfigUpdate,
        AIAgentConfigsPublic=AIAgentConfigsPublic,
        CompanyLLMApiKeyPublic=CompanyLLMApiKeyPublic,
        CompanyLLMApiKeyCreate=CompanyLLMApiKeyCreate,
        CompanyLLMApiKeysPublic=CompanyLLMApiKeysPublic,
        Message=Message,
        log_audit=log_audit,
        get_key_store=get_key_store_fn if get_key_store_fn is not None else get_key_store,
    )
    if with_sync:
        kwargs.update(
            InternalServiceDep=InternalServiceDep,
            AIAgentSyncRequest=AIAgentSyncRequest,
            AIAgentSyncResponse=AIAgentSyncResponse,
            AIAgentSyncResultItem=AIAgentSyncResultItem,
        )
    return create_agents_router(**kwargs)


def _make_skills_router(*, with_sync: bool = False):
    """Build the smart-llm skills router from the factory (no HTTP client).

    When ``with_sync=True``, the optional vertical-app sync parameters are
    injected so the ``POST /ai-skills/sync`` route is registered. Existing
    tests that expect only the user-facing CRUD routes leave it False.
    """
    from smart_llm.api.routers.skills import create_skills_router

    from integration_hub_backend.api.api.deps import (
        CompanyAdminDep,
        CurrentUser,
        InternalServiceDep,
        SessionDep,
    )
    from integration_hub_backend.api.core.audit import log_audit
    from integration_hub_backend.api.models.ai_agent import (
        AISkill,
        AISkillCreate,
        AISkillPublic,
        AISkillsPublic,
        AISkillSyncRequest,
        AISkillSyncResponse,
        AISkillSyncResultItem,
        AISkillUpdate,
        Message,
    )

    kwargs = dict(
        SessionDep=SessionDep,
        CurrentUser=CurrentUser,
        CompanyAdminDep=CompanyAdminDep,
        AISkill=AISkill,
        AISkillPublic=AISkillPublic,
        AISkillCreate=AISkillCreate,
        AISkillUpdate=AISkillUpdate,
        AISkillsPublic=AISkillsPublic,
        Message=Message,
        log_audit=log_audit,
    )
    if with_sync:
        kwargs.update(
            InternalServiceDep=InternalServiceDep,
            AISkillSyncRequest=AISkillSyncRequest,
            AISkillSyncResponse=AISkillSyncResponse,
            AISkillSyncResultItem=AISkillSyncResultItem,
        )
    return create_skills_router(**kwargs)


def _make_mock_user():
    from integration_hub_backend.api.api.deps import CurrentUserPayload

    return CurrentUserPayload(
        user_id=USER_ID,
        company_id=COMPANY_ID,
        role="company_admin",
        email="admin@example.com",
    )


def _get_handler(router, path_suffix: str, method: str):
    """Return the endpoint coroutine for a route identified by path suffix + HTTP method.

    The smart-llm routers embed their prefix in each route path, so we match
    on the suffix (e.g. '/' matches '/ai-agents/', '/{config_id}' matches
    '/ai-agents/{config_id}').
    """
    for r in router.routes:
        if r.path.endswith(path_suffix) and method in r.methods:
            return r.endpoint
    available = [(r.path, r.methods) for r in router.routes]
    raise AssertionError(
        f"No route matching suffix={path_suffix!r} method={method!r}. Available: {available}"
    )


# Note: The smart-llm router factories use `from __future__ import annotations`,
# which causes FastAPI's DI resolution to treat injected type aliases as plain
# query params when used through a TestClient.  We therefore call the route
# handler coroutines directly — bypassing HTTP — which is the correct unit-test
# pattern for factory-built routers.


class TestAgentConfigRoutes:
    @pytest.mark.asyncio
    async def test_list_agent_configs_empty(self):
        """list_agent_configs returns an empty list when no configs exist."""
        router = _make_agents_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        # Grab the handler for GET /
        handler = _get_handler(router, "/", "GET")

        mock_result_count = MagicMock()
        mock_result_count.scalar_one.return_value = 0
        mock_result_list = MagicMock()
        mock_result_list.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[mock_result_count, mock_result_list])

        result = await handler(
            session=mock_session, current_user=mock_user, skip=0, limit=100, search=None
        )
        assert result.count == 0
        assert result.data == []

    @pytest.mark.asyncio
    async def test_get_agent_config_not_found(self):
        """get_agent_config raises 404 when the config doesn't exist."""
        from fastapi import HTTPException

        router = _make_agents_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/{config_id}", "GET")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await handler(session=mock_session, current_user=mock_user, config_id=AGENT_CONFIG_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_agent_config_not_found(self):
        """delete_agent_config raises 404 when the config doesn't exist."""
        from fastapi import HTTPException

        router = _make_agents_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/{config_id}", "DELETE")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await handler(session=mock_session, current_user=mock_user, config_id=AGENT_CONFIG_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_agent_config(self):
        """create_agent_config persists a config and returns the public schema."""
        from integration_hub_backend.api.models.ai_agent import AIAgentConfigCreate

        router = _make_agents_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        now = datetime.now(UTC)

        mock_config = MagicMock()
        mock_config.id = AGENT_CONFIG_ID
        mock_config.company_id = COMPANY_ID
        mock_config.name = "my-agent"
        mock_config.label = None
        mock_config.description = None
        mock_config.icon = None
        mock_config.system_prompt = "Be helpful."
        mock_config.provider_type = "anthropic"
        mock_config.model_name = "claude-3-5-sonnet-20240620"
        mock_config.model_configuration = None
        mock_config.response_format = None
        mock_config.role_id = None
        mock_config.is_active = True
        mock_config.created_at = now
        mock_config.created_by = USER_ID
        mock_config.skill_links = []
        mock_config.__table__ = MagicMock()
        mock_config.__table__.columns = [
            MagicMock(key=k)
            for k in (
                "id",
                "company_id",
                "name",
                "label",
                "description",
                "icon",
                "system_prompt",
                "provider_type",
                "model_name",
                "model_configuration",
                "response_format",
                "role_id",
                "is_active",
                "created_at",
                "created_by",
            )
        ]

        mock_result = MagicMock()
        mock_result.scalars.return_value.one.return_value = mock_config
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        mock_session.add = MagicMock()

        handler = _get_handler(router, "/", "POST")
        data = AIAgentConfigCreate(
            name="my-agent",
            system_prompt="Be helpful.",
            provider_type="anthropic",
            model_name="claude-3-5-sonnet-20240620",
        )
        result = await handler(session=mock_session, current_user=mock_user, data=data)

        assert result.name == "my-agent"
        assert result.provider_type == "anthropic"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_llm_keys(self):
        """list_llm_keys returns keys from the smart-llm key store."""

        now = datetime.now(UTC).isoformat()
        mock_keys = [
            {"id": str(LLM_KEY_ID), "provider": "anthropic", "is_active": True, "created_at": now},
        ]
        mock_store = AsyncMock()
        mock_store.list_keys = AsyncMock(return_value=mock_keys)

        # Inject the mock store factory at router-build time so the closure
        # captures our mock rather than the real singleton.
        router = _make_agents_router(get_key_store_fn=lambda: mock_store)
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/llm-keys/", "GET")
        result = await handler(session=mock_session, current_user=mock_user)

        assert result.count == 1
        assert result.data[0].provider == "anthropic"
        assert result.data[0].is_active is True

    @pytest.mark.asyncio
    async def test_create_llm_key(self):
        """create_llm_key stores a new key and returns the public schema."""
        from integration_hub_backend.api.models.ai_agent import CompanyLLMApiKeyCreate

        now = datetime.now(UTC).isoformat()
        saved = {
            "id": str(LLM_KEY_ID),
            "provider": "anthropic",
            "is_active": True,
            "created_at": now,
        }
        mock_store = AsyncMock()
        mock_store.save_key = AsyncMock(return_value=saved)

        router = _make_agents_router(get_key_store_fn=lambda: mock_store)
        mock_user = _make_mock_user()
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        handler = _get_handler(router, "/llm-keys/", "POST")
        data = CompanyLLMApiKeyCreate(provider="anthropic", api_key="sk-ant-real-key")
        result = await handler(session=mock_session, current_user=mock_user, data=data)

        assert result.provider == "anthropic"
        assert result.is_active is True
        mock_store.save_key.assert_called_once_with(
            "anthropic",
            "sk-ant-real-key",
            label="anthropic key",
            scope_id=COMPANY_ID,
        )

    @pytest.mark.asyncio
    async def test_delete_llm_key_not_found(self):
        """delete_llm_key raises 404 when the key doesn't exist in the store."""
        from fastapi import HTTPException

        mock_store = AsyncMock()
        mock_store.list_keys = AsyncMock(return_value=[])

        router = _make_agents_router(get_key_store_fn=lambda: mock_store)
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/llm-keys/{key_id}", "DELETE")

        with pytest.raises(HTTPException) as exc_info:
            await handler(session=mock_session, current_user=mock_user, key_id=LLM_KEY_ID)

        assert exc_info.value.status_code == 404

    def test_router_has_expected_routes(self):
        """Smoke test: the agents router must expose the expected URL patterns."""
        router = _make_agents_router()
        paths = {r.path for r in router.routes}
        # Paths include the /ai-agents prefix set by the factory
        assert any(p.endswith("/") and "agents" in p for p in paths), paths
        assert any("config_id" in p for p in paths), paths
        assert any("llm-keys/" in p for p in paths), paths
        assert any("key_id" in p for p in paths), paths


# ─────────────────────────────────────────────────────────────────────────────
# 6. /ai-skills/ CRUD routes
# ─────────────────────────────────────────────────────────────────────────────


class TestSkillRoutes:
    @pytest.mark.asyncio
    async def test_list_skills_empty(self):
        """list_skills returns an empty list when no skills exist."""
        router = _make_skills_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/", "GET")

        mock_result_count = MagicMock()
        mock_result_count.scalar_one.return_value = 0
        mock_result_list = MagicMock()
        mock_result_list.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[mock_result_count, mock_result_list])

        result = await handler(
            session=mock_session, current_user=mock_user, skip=0, limit=100, search=None
        )
        assert result.count == 0
        assert result.data == []

    @pytest.mark.asyncio
    async def test_list_skills_with_search(self):
        """list_skills with a search string still returns an AISkillsPublic."""
        router = _make_skills_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/", "GET")

        mock_result_count = MagicMock()
        mock_result_count.scalar_one.return_value = 0
        mock_result_list = MagicMock()
        mock_result_list.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[mock_result_count, mock_result_list])

        result = await handler(
            session=mock_session, current_user=mock_user, skip=0, limit=100, search="pii"
        )
        assert result.count == 0

    @pytest.mark.asyncio
    async def test_get_skill_not_found(self):
        """get_skill raises 404 when the skill doesn't exist."""
        from fastapi import HTTPException

        router = _make_skills_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/{skill_id}", "GET")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await handler(session=mock_session, current_user=mock_user, skill_id=SKILL_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_skill_not_found(self):
        """delete_skill raises 404 when the skill doesn't exist."""
        from fastapi import HTTPException

        router = _make_skills_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/{skill_id}", "DELETE")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await handler(session=mock_session, current_user=mock_user, skill_id=SKILL_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_skill_not_found(self):
        """update_skill raises 404 when the skill doesn't exist."""
        from fastapi import HTTPException

        from integration_hub_backend.api.models.ai_agent import AISkillUpdate

        router = _make_skills_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()

        handler = _get_handler(router, "/{skill_id}", "PATCH")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await handler(
                session=mock_session,
                current_user=mock_user,
                skill_id=SKILL_ID,
                data=AISkillUpdate(name="x"),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_skill(self):
        """create_skill adds a new skill and returns the public schema."""
        from integration_hub_backend.api.models.ai_agent import AISkillCreate, AISkillPublic

        router = _make_skills_router()
        mock_user = _make_mock_user()
        mock_session = AsyncMock()
        now = datetime.now(UTC)

        # The handler calls session.add, log_audit, session.commit, session.refresh,
        # then AISkillPublic.model_validate(skill).
        created_skill = MagicMock()
        created_skill.id = SKILL_ID
        created_skill.company_id = COMPANY_ID
        created_skill.name = "pii-filter"
        created_skill.label = "PII Filter"
        created_skill.description = None
        created_skill.icon = None
        created_skill.content = "Strip PII."
        created_skill.is_active = True
        created_skill.created_at = now

        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        handler = _get_handler(router, "/", "POST")
        data = AISkillCreate(name="pii-filter", label="PII Filter", content="Strip PII.")

        with patch(
            "integration_hub_backend.api.models.ai_agent.AISkillPublic.model_validate",
            return_value=AISkillPublic(
                id=SKILL_ID,
                company_id=COMPANY_ID,
                name="pii-filter",
                is_active=True,
                created_at=now,
            ),
        ):
            result = await handler(session=mock_session, current_user=mock_user, data=data)

        assert result.name == "pii-filter"
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_router_has_expected_routes(self):
        """Smoke test: the skills router must expose the expected URL patterns."""
        router = _make_skills_router()
        paths = {r.path for r in router.routes}
        assert any(p.endswith("/") and "skills" in p for p in paths), paths
        assert any("skill_id" in p for p in paths), paths


# ─────────────────────────────────────────────────────────────────────────────
# 7. audit log helper
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_audit_does_not_raise():
    """log_audit must complete without raising even with a mock session."""
    from integration_hub_backend.api.core.audit import log_audit

    mock_session = AsyncMock()
    # Should not raise
    await log_audit(
        mock_session,
        user_id=USER_ID,
        company_id=COMPANY_ID,
        action="ai_skill.created",
        target_type="ai_skill",
        target_id=str(SKILL_ID),
        details={"name": "test"},
    )


@pytest.mark.asyncio
async def test_log_audit_no_details():
    """log_audit must handle missing details gracefully."""
    from integration_hub_backend.api.core.audit import log_audit

    mock_session = AsyncMock()
    await log_audit(
        mock_session,
        user_id=USER_ID,
        company_id=COMPANY_ID,
        action="ai_agent_config.deleted",
        target_type="ai_agent_config",
        target_id=str(AGENT_CONFIG_ID),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Vertical-app skill sync (POST /ai-skills/sync) + managed-skill guards
# ─────────────────────────────────────────────────────────────────────────────


def _make_managed_skill(*, source_app: str = "restoration", **overrides):
    """Build a mock AISkill ORM row that looks like one provisioned by sync."""
    skill = MagicMock()
    skill.id = overrides.get("id", uuid.uuid4())
    skill.company_id = COMPANY_ID
    skill.name = overrides.get("name", f"{source_app}:photo_tagger")
    skill.label = overrides.get("label", None)
    skill.description = overrides.get("description", None)
    skill.icon = overrides.get("icon", None)
    skill.kind = overrides.get("kind", "prompt")
    skill.modality = overrides.get("modality", "any")
    skill.content = overrides.get("content", "You are a photo tagger.")
    skill.source_app = source_app
    skill.is_active = True
    return skill


class TestSkillSyncRoute:
    """Sync endpoint is M2M-only and creates/updates skills with source_app set."""

    def test_sync_route_only_registered_when_params_supplied(self):
        """Default factory call (no sync params) leaves /sync unregistered."""
        router_no_sync = _make_skills_router()
        paths = {r.path for r in router_no_sync.routes}
        assert not any(p.endswith("/sync") for p in paths), paths

        router_with_sync = _make_skills_router(with_sync=True)
        paths_with = {r.path for r in router_with_sync.routes}
        assert any(p.endswith("/sync") for p in paths_with), paths_with

    @pytest.mark.asyncio
    async def test_sync_creates_new_skills(self):
        """Skills with no DB match are inserted, namespaced by source_app."""
        from integration_hub_backend.api.models.ai_agent import (
            AISkillSyncItem,
            AISkillSyncRequest,
        )

        router = _make_skills_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        mock_session = AsyncMock()
        # First execute() returns the existing-rows lookup → empty
        mock_lookup = MagicMock()
        mock_lookup.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_lookup)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        request = AISkillSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            skills=[
                AISkillSyncItem(name="photo_tagger", content="prompt body"),
                AISkillSyncItem(name="memo_structurer", content="memo prompt"),
            ],
        )

        result = await handler(session=mock_session, _=True, data=request)

        assert result.source_app == "restoration"
        assert len(result.created) == 2
        assert {item.name for item in result.created} == {
            "restoration:photo_tagger",
            "restoration:memo_structurer",
        }
        # All inserts go through one commit
        mock_session.commit.assert_awaited_once()
        # Two add() calls, one per new skill
        assert mock_session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_sync_updates_changed_skills(self):
        """Skills whose content changed are updated; same-content rows stay unchanged."""
        from integration_hub_backend.api.models.ai_agent import (
            AISkillSyncItem,
            AISkillSyncRequest,
        )

        router = _make_skills_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        # One existing row with the SAME content; one with DIFFERENT content
        unchanged_row = _make_managed_skill(name="restoration:photo_tagger", content="same prompt")
        stale_row = _make_managed_skill(name="restoration:memo_structurer", content="OLD prompt")

        mock_session = AsyncMock()
        mock_lookup = MagicMock()
        mock_lookup.scalars.return_value.all.return_value = [unchanged_row, stale_row]
        mock_session.execute = AsyncMock(return_value=mock_lookup)
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        request = AISkillSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            skills=[
                AISkillSyncItem(name="photo_tagger", content="same prompt"),
                AISkillSyncItem(name="memo_structurer", content="NEW prompt"),
            ],
        )

        result = await handler(session=mock_session, _=True, data=request)

        assert len(result.unchanged) == 1
        assert result.unchanged[0].name == "restoration:photo_tagger"
        assert len(result.updated) == 1
        assert result.updated[0].name == "restoration:memo_structurer"
        # The stale row's content was mutated in place
        assert stale_row.content == "NEW prompt"

    @pytest.mark.asyncio
    async def test_sync_rejects_cross_app_conflict(self):
        """If a skill exists with a different source_app, sync aborts with 409."""
        from fastapi import HTTPException

        from integration_hub_backend.api.models.ai_agent import (
            AISkillSyncItem,
            AISkillSyncRequest,
        )

        router = _make_skills_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        # Existing row owned by a different app
        foreign_row = _make_managed_skill(
            source_app="cooling-tower",
            name="restoration:photo_tagger",  # name collision via spoof attempt
        )

        mock_session = AsyncMock()
        mock_lookup = MagicMock()
        mock_lookup.scalars.return_value.all.return_value = [foreign_row]
        mock_session.execute = AsyncMock(return_value=mock_lookup)

        request = AISkillSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            skills=[AISkillSyncItem(name="photo_tagger", content="x")],
        )

        with pytest.raises(HTTPException) as exc:
            await handler(session=mock_session, _=True, data=request)
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "source_app_conflict"
        assert exc.value.detail["owning_app"] == "cooling-tower"
        # No commit — atomic abort
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_empty_batch_is_noop(self):
        """An empty skills list returns successfully with all-empty buckets."""
        from integration_hub_backend.api.models.ai_agent import AISkillSyncRequest

        router = _make_skills_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        mock_session = AsyncMock()
        request = AISkillSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            skills=[],
        )
        result = await handler(session=mock_session, _=True, data=request)
        assert result.created == []
        assert result.updated == []
        assert result.unchanged == []

    @pytest.mark.asyncio
    async def test_sync_rejects_empty_source_app(self):
        """Empty source_app is a malformed request — 400."""
        from fastapi import HTTPException

        from integration_hub_backend.api.models.ai_agent import (
            AISkillSyncItem,
            AISkillSyncRequest,
        )

        router = _make_skills_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        request = AISkillSyncRequest(
            source_app="",
            company_id=COMPANY_ID,
            skills=[AISkillSyncItem(name="x", content="y")],
        )
        mock_session = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await handler(session=mock_session, _=True, data=request)
        assert exc.value.status_code == 400


class TestManagedSkillGuards:
    """PATCH and DELETE on a skill with source_app != None must return 403."""

    @pytest.mark.asyncio
    async def test_patch_managed_skill_returns_403(self):
        from fastapi import HTTPException

        from integration_hub_backend.api.models.ai_agent import AISkillUpdate

        router = _make_skills_router()
        handler = _get_handler(router, "/{skill_id}", "PATCH")

        managed = _make_managed_skill(source_app="restoration")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = managed
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc:
            await handler(
                session=mock_session,
                current_user=_make_mock_user(),
                skill_id=managed.id,
                data=AISkillUpdate(content="hijack"),
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "managed_skill"
        assert exc.value.detail["source_app"] == "restoration"
        # Mutations never committed
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_managed_skill_returns_403(self):
        from fastapi import HTTPException

        router = _make_skills_router()
        handler = _get_handler(router, "/{skill_id}", "DELETE")

        managed = _make_managed_skill(source_app="restoration")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = managed
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc:
            await handler(
                session=mock_session,
                current_user=_make_mock_user(),
                skill_id=managed.id,
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "managed_skill"
        mock_session.delete.assert_not_called()
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_patch_unmanaged_skill_still_works(self):
        """Skills with source_app=None remain editable through the UI."""
        from integration_hub_backend.api.models.ai_agent import AISkillPublic, AISkillUpdate

        router = _make_skills_router()
        handler = _get_handler(router, "/{skill_id}", "PATCH")

        unmanaged = _make_managed_skill(source_app=None, name="hand-authored")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = unmanaged
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        now = datetime.now(UTC)

        with patch(
            "integration_hub_backend.api.models.ai_agent.AISkillPublic.model_validate",
            return_value=AISkillPublic(
                id=unmanaged.id,
                company_id=COMPANY_ID,
                name="hand-authored",
                content="updated",
                is_active=True,
                created_at=now,
            ),
        ):
            result = await handler(
                session=mock_session,
                current_user=_make_mock_user(),
                skill_id=unmanaged.id,
                data=AISkillUpdate(content="updated"),
            )

        assert result.content == "updated"
        mock_session.commit.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# 9. Vertical-app agent sync (POST /ai-agents/sync) + managed-agent guards
# ─────────────────────────────────────────────────────────────────────────────


def _make_managed_agent(
    *,
    source_app: str = "restoration",
    skill_link_skill_ids=None,
    **overrides,
):
    """Build a mock AIAgentConfig ORM row that looks like one provisioned by sync."""
    config = MagicMock()
    config.id = overrides.get("id", uuid.uuid4())
    config.company_id = COMPANY_ID
    config.name = overrides.get("name", f"{source_app}:photo_triage")
    config.label = overrides.get("label", None)
    config.description = overrides.get("description", None)
    config.icon = overrides.get("icon", None)
    config.system_prompt = overrides.get("system_prompt", "Triage prompt.")
    config.provider_type = overrides.get("provider_type", "anthropic")
    config.model_name = overrides.get("model_name", "claude-sonnet-4-6")
    config.model_configuration = overrides.get("model_configuration", None)
    config.response_format = overrides.get("response_format", "json")
    config.source_app = source_app
    config.is_active = True
    # skill_links — list of mock link rows with skill_id
    skill_link_skill_ids = skill_link_skill_ids or []
    config.skill_links = [MagicMock(skill_id=sid) for sid in skill_link_skill_ids]
    return config


class TestAgentSyncRoute:
    """Sync endpoint creates/updates agents with source_app + skill_link diff."""

    def test_sync_route_only_registered_when_params_supplied(self):
        router_no_sync = _make_agents_router()
        paths = {r.path for r in router_no_sync.routes}
        assert not any(p.endswith("/sync") for p in paths), paths

        router_with_sync = _make_agents_router(with_sync=True)
        paths_with = {r.path for r in router_with_sync.routes}
        assert any(p.endswith("/sync") for p in paths_with), paths_with

    @pytest.mark.asyncio
    async def test_sync_creates_new_agent_with_skill_links(self):
        from integration_hub_backend.api.models.ai_agent import (
            AIAgentSyncItem,
            AIAgentSyncRequest,
        )

        router = _make_agents_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        # Pre-existing skill row that the new agent will attach to.
        # NOTE: MagicMock(name=...) sets the mock's repr, not a .name attribute.
        # Set .name explicitly after construction.
        skill_id = uuid.uuid4()
        skill_row = MagicMock(id=skill_id)
        skill_row.name = "restoration:photo_tagger"

        mock_session = AsyncMock()
        # First execute() — agent lookup → empty
        # Second execute() — skill resolution → returns the skill_row
        agent_lookup = MagicMock()
        agent_lookup.scalars.return_value.all.return_value = []
        skill_lookup = MagicMock()
        skill_lookup.scalars.return_value.all.return_value = [skill_row]
        mock_session.execute = AsyncMock(side_effect=[agent_lookup, skill_lookup])
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        request = AIAgentSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            agents=[
                AIAgentSyncItem(
                    name="photo_triage",
                    system_prompt="Triage photos.",
                    skill_names=["photo_tagger"],  # bare → "restoration:photo_tagger"
                ),
            ],
        )
        result = await handler(session=mock_session, _=True, data=request)

        assert len(result.created) == 1
        created = result.created[0]
        assert created.name == "restoration:photo_triage"
        assert created.unresolved_skills == []

        # session.add called with (1) the AIAgentConfig + (2) the AIAgentSkillLink
        assert mock_session.add.call_count == 2
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_reports_unresolved_skills_without_failing(self):
        from integration_hub_backend.api.models.ai_agent import (
            AIAgentSyncItem,
            AIAgentSyncRequest,
        )

        router = _make_agents_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        mock_session = AsyncMock()
        agent_lookup = MagicMock()
        agent_lookup.scalars.return_value.all.return_value = []
        # Skill lookup returns nothing — referenced skill doesn't exist yet
        skill_lookup = MagicMock()
        skill_lookup.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[agent_lookup, skill_lookup])
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        request = AIAgentSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            agents=[
                AIAgentSyncItem(
                    name="photo_triage",
                    skill_names=["does_not_exist", "smart_llm:also_missing"],
                ),
            ],
        )
        result = await handler(session=mock_session, _=True, data=request)

        # Agent is still created, but with unresolved_skills surfaced
        assert len(result.created) == 1
        unresolved = result.created[0].unresolved_skills
        assert "restoration:does_not_exist" in unresolved
        assert "smart_llm:also_missing" in unresolved
        # Only the agent was added — no link rows
        assert mock_session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_sync_updates_changed_agent(self):
        from integration_hub_backend.api.models.ai_agent import (
            AIAgentSyncItem,
            AIAgentSyncRequest,
        )

        router = _make_agents_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        existing = _make_managed_agent(
            source_app="restoration",
            name="restoration:photo_triage",
            system_prompt="OLD prompt",
        )
        mock_session = AsyncMock()
        agent_lookup = MagicMock()
        agent_lookup.scalars.return_value.all.return_value = [existing]
        skill_lookup = MagicMock()
        skill_lookup.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[agent_lookup, skill_lookup])
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        request = AIAgentSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            agents=[
                AIAgentSyncItem(
                    name="photo_triage",
                    system_prompt="NEW prompt",  # changed
                    skill_names=[],
                ),
            ],
        )
        result = await handler(session=mock_session, _=True, data=request)

        assert len(result.updated) == 1
        assert result.unchanged == []
        assert existing.system_prompt == "NEW prompt"  # mutated in place

    @pytest.mark.asyncio
    async def test_sync_unchanged_when_nothing_differs(self):
        from integration_hub_backend.api.models.ai_agent import (
            AIAgentSyncItem,
            AIAgentSyncRequest,
        )

        router = _make_agents_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        existing = _make_managed_agent(
            source_app="restoration",
            name="restoration:photo_triage",
            label=None,
            description=None,
            icon=None,
            system_prompt="Same prompt",
            provider_type="anthropic",
            model_name="claude-sonnet-4-6",
            model_configuration=None,
            response_format=None,
            skill_link_skill_ids=[],
        )
        mock_session = AsyncMock()
        agent_lookup = MagicMock()
        agent_lookup.scalars.return_value.all.return_value = [existing]
        skill_lookup = MagicMock()
        skill_lookup.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[agent_lookup, skill_lookup])
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        request = AIAgentSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            agents=[
                AIAgentSyncItem(
                    name="photo_triage",
                    system_prompt="Same prompt",
                    provider_type="anthropic",
                    model_name="claude-sonnet-4-6",
                ),
            ],
        )
        result = await handler(session=mock_session, _=True, data=request)

        assert len(result.unchanged) == 1
        assert result.created == []
        assert result.updated == []

    @pytest.mark.asyncio
    async def test_sync_rejects_cross_app_conflict(self):
        from fastapi import HTTPException

        from integration_hub_backend.api.models.ai_agent import (
            AIAgentSyncItem,
            AIAgentSyncRequest,
        )

        router = _make_agents_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        foreign = _make_managed_agent(
            source_app="cooling-tower",
            name="restoration:photo_triage",  # name spoof
        )
        mock_session = AsyncMock()
        agent_lookup = MagicMock()
        agent_lookup.scalars.return_value.all.return_value = [foreign]
        mock_session.execute = AsyncMock(return_value=agent_lookup)

        request = AIAgentSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            agents=[AIAgentSyncItem(name="photo_triage")],
        )
        with pytest.raises(HTTPException) as exc:
            await handler(session=mock_session, _=True, data=request)
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "source_app_conflict"
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_empty_batch_is_noop(self):
        from integration_hub_backend.api.models.ai_agent import AIAgentSyncRequest

        router = _make_agents_router(with_sync=True)
        handler = _get_handler(router, "/sync", "POST")

        mock_session = AsyncMock()
        request = AIAgentSyncRequest(
            source_app="restoration",
            company_id=COMPANY_ID,
            agents=[],
        )
        result = await handler(session=mock_session, _=True, data=request)
        assert result.created == []
        assert result.updated == []
        assert result.unchanged == []


class TestManagedAgentGuards:
    """PATCH/DELETE on agents with source_app != None must return 403."""

    @pytest.mark.asyncio
    async def test_patch_managed_agent_returns_403(self):
        from fastapi import HTTPException

        from integration_hub_backend.api.models.ai_agent import AIAgentConfigUpdate

        router = _make_agents_router()
        handler = _get_handler(router, "/{config_id}", "PATCH")

        managed = _make_managed_agent(source_app="restoration")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = managed
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc:
            await handler(
                session=mock_session,
                current_user=_make_mock_user(),
                config_id=managed.id,
                data=AIAgentConfigUpdate(system_prompt="hijack"),
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "managed_agent"
        assert exc.value.detail["source_app"] == "restoration"
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_managed_agent_returns_403(self):
        from fastapi import HTTPException

        router = _make_agents_router()
        handler = _get_handler(router, "/{config_id}", "DELETE")

        managed = _make_managed_agent(source_app="restoration")
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = managed
        mock_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc:
            await handler(
                session=mock_session,
                current_user=_make_mock_user(),
                config_id=managed.id,
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "managed_agent"
        mock_session.delete.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Phase B — AIService.complete() agent_id branch + AgentRunRequest validation
# ─────────────────────────────────────────────────────────────────────────────


class TestAIServiceAgentIdResolution:
    """``_resolve_agent_config`` must accept either ``agent_name`` or
    ``agent_id``. Workflow nodes store the UUID; human callers use the name.
    """

    @pytest.mark.asyncio
    async def test_resolve_by_agent_id_returns_config_and_skills(self):
        from integration_hub_backend.api.services.ai_service import AIService

        agent_id = uuid.uuid4()
        cfg = MagicMock()
        cfg.id = agent_id
        cfg.company_id = COMPANY_ID
        cfg.is_active = True

        # session.get(AIAgentConfig, agent_id) → returns the row
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=cfg)
        # session.execute(...).all() → empty skill list
        mock_skill_result = MagicMock()
        mock_skill_result.all = MagicMock(return_value=[])
        mock_session.execute = AsyncMock(return_value=mock_skill_result)

        service = AIService(mock_session)
        result_cfg, skills, skill_ids = await service._resolve_agent_config(
            COMPANY_ID, agent_id=agent_id
        )

        assert result_cfg is cfg
        assert skills == []
        assert skill_ids == []
        mock_session.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_by_agent_id_wrong_company_raises(self):
        """An agent owned by company A must not resolve for company B."""
        from integration_hub_backend.api.services.ai_service import AIService

        agent_id = uuid.uuid4()
        other_company = uuid.uuid4()
        cfg = MagicMock()
        cfg.id = agent_id
        cfg.company_id = other_company  # different tenant
        cfg.is_active = True

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=cfg)

        service = AIService(mock_session)
        with pytest.raises(ValueError, match="not found for company"):
            await service._resolve_agent_config(COMPANY_ID, agent_id=agent_id)

    @pytest.mark.asyncio
    async def test_resolve_by_agent_id_missing_raises(self):
        from integration_hub_backend.api.services.ai_service import AIService

        agent_id = uuid.uuid4()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        service = AIService(mock_session)
        with pytest.raises(ValueError, match="not found for company"):
            await service._resolve_agent_config(COMPANY_ID, agent_id=agent_id)

    @pytest.mark.asyncio
    async def test_resolve_by_agent_id_inactive_raises(self):
        from integration_hub_backend.api.services.ai_service import AIService

        agent_id = uuid.uuid4()
        cfg = MagicMock()
        cfg.id = agent_id
        cfg.company_id = COMPANY_ID
        cfg.is_active = False  # explicitly disabled

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=cfg)

        service = AIService(mock_session)
        with pytest.raises(ValueError, match="inactive"):
            await service._resolve_agent_config(COMPANY_ID, agent_id=agent_id)

    @pytest.mark.asyncio
    async def test_resolve_by_neither_returns_none(self):
        """No agent_name AND no agent_id → fall back to no-agent path."""
        from integration_hub_backend.api.services.ai_service import AIService

        mock_session = AsyncMock()
        service = AIService(mock_session)
        cfg, skills, skill_ids = await service._resolve_agent_config(COMPANY_ID)
        assert cfg is None
        assert skills == []
        assert skill_ids == []

    @pytest.mark.asyncio
    async def test_resolve_by_agent_name_still_works(self):
        """Backward-compat: agent_name resolution path is unchanged."""
        from integration_hub_backend.api.services.ai_service import AIService

        cfg = MagicMock()
        cfg.id = uuid.uuid4()
        cfg.company_id = COMPANY_ID
        cfg.is_active = True

        # First execute() → SELECT AIAgentConfig (returns scalar_one_or_none cfg)
        # Second execute() → SELECT AISkill names (returns .all() = [])
        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none = MagicMock(return_value=cfg)
        skill_result = MagicMock()
        skill_result.all = MagicMock(return_value=[])

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[cfg_result, skill_result])

        service = AIService(mock_session)
        result_cfg, skills, skill_ids = await service._resolve_agent_config(
            COMPANY_ID, agent_name="my-agent"
        )
        assert result_cfg is cfg
        assert skills == []
        assert skill_ids == []


class TestAuthoringRestrictedToPlatformAdmin:
    """Tenants are consumers, not authors: on the WIRED app router, the skill/
    agent/LLM-key authoring routes must depend on ``require_platform_admin``
    (not ``require_company_admin``), while the read routes stay company-admin.
    Introspects the real ``api_router`` so it reflects production wiring."""

    @staticmethod
    def _dep_calls(route) -> set:
        names: set[str] = set()

        def walk(dep):
            if getattr(dep, "call", None) is not None:
                names.add(getattr(dep.call, "__name__", str(dep.call)))
            for sub in getattr(dep, "dependencies", []) or []:
                walk(sub)

        walk(route.dependant)
        return names

    def _route(self, path: str, method: str):
        from integration_hub_backend.api.api.main import api_router

        for r in api_router.routes:
            if getattr(r, "path", None) == path and method in (
                getattr(r, "methods", set()) or set()
            ):
                return r
        raise AssertionError(f"route {method} {path} not found")

    @pytest.mark.parametrize(
        "path,method",
        [
            ("/ai-skills/", "POST"),
            ("/ai-skills/{skill_id}", "PATCH"),
            ("/ai-skills/{skill_id}", "DELETE"),
            ("/ai-agents/", "POST"),
            ("/ai-agents/{config_id}", "PATCH"),
            ("/ai-agents/{config_id}", "DELETE"),
            ("/ai-agents/llm-keys/", "POST"),
            ("/ai-agents/llm-keys/{key_id}", "DELETE"),
        ],
    )
    def test_authoring_routes_require_platform_admin(self, path, method):
        calls = self._dep_calls(self._route(path, method))
        assert "require_platform_admin" in calls, f"{method} {path} deps={calls}"
        assert "require_company_admin" not in calls

    @pytest.mark.parametrize("path", ["/ai-skills/", "/ai-agents/"])
    def test_list_routes_stay_company_admin(self, path):
        calls = self._dep_calls(self._route(path, "GET"))
        assert "require_company_admin" in calls
        assert "require_platform_admin" not in calls


class TestSourceAppDeploymentGuard:
    """Per-deployment domain isolation: /sync only ingests THIS deployment's
    domain. A restoration deployment must reject a wealth sync (and vice-versa);
    with no APP_SOURCE configured, any domain is accepted (back-compat)."""

    def _sync(self, deployment_app, request_app):
        from fastapi import FastAPI
        from smart_llm.api.routers.skills import create_skills_router

        from integration_hub_backend.api.api import deps as D
        from integration_hub_backend.api.models import ai_agent as M

        router = create_skills_router(
            SessionDep=D.SessionDep,
            CurrentUser=D.CurrentUser,
            CompanyAdminDep=D.CompanyAdminDep,
            PlatformAdminDep=D.PlatformAdminDep,
            expected_source_app=deployment_app,
            AISkill=M.AISkill,
            AISkillPublic=M.AISkillPublic,
            AISkillCreate=M.AISkillCreate,
            AISkillUpdate=M.AISkillUpdate,
            AISkillsPublic=M.AISkillsPublic,
            Message=M.Message,
            log_audit=lambda *a, **k: None,
            InternalServiceDep=D.InternalServiceDep,
            AISkillSyncRequest=M.AISkillSyncRequest,
            AISkillSyncResponse=M.AISkillSyncResponse,
            AISkillSyncResultItem=M.AISkillSyncResultItem,
            AISkillGrant=M.AISkillGrant,
        )
        app = FastAPI()
        app.include_router(router)
        mock_session = AsyncMock()

        async def _mock_db():
            yield mock_session

        app.dependency_overrides[D.require_internal_service] = lambda: True
        app.dependency_overrides[D.get_db] = _mock_db
        client = TestClient(app)
        return client.post(
            "/ai-skills/sync",
            json={"source_app": request_app, "company_id": str(COMPANY_ID), "skills": []},
            headers={"Authorization": "Bearer internal"},
        )

    def test_rejects_foreign_domain(self):
        r = self._sync("restoration", "wealth")
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "wrong_deployment"

    def test_accepts_own_domain(self):
        # Own-domain sync with an empty batch is a valid no-op → 200.
        assert self._sync("restoration", "restoration").status_code == 200

    def test_unset_app_source_allows_any(self):
        assert self._sync(None, "wealth").status_code == 200


class TestNonAutonomousPolicyGate:
    """The standard (non-autonomous) invoke path must gate ActionTool calls:
    ``_build_policy_gate`` returns a deny-by-default gate when the agent binds
    tools, and None when it binds none (a pure prompt agent needs no gate)."""

    @pytest.mark.asyncio
    async def test_no_gate_when_agent_has_no_tool_bindings(self):
        from integration_hub_backend.api.services.ai_service import AIService

        cfg = MagicMock()
        cfg.id = uuid.uuid4()
        rows = MagicMock()
        rows.all = MagicMock(return_value=[])  # no skill/tool links
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=rows)

        gate = await AIService(mock_session)._build_policy_gate(cfg, str(COMPANY_ID))
        assert gate is None

    @pytest.mark.asyncio
    async def test_gate_built_with_tool_modes_when_tools_bound(self):
        from smart_llm.security.tool_policy import ToolPolicyGate

        from integration_hub_backend.api.services.ai_service import AIService

        cfg = MagicMock()
        cfg.id = uuid.uuid4()
        rows = MagicMock()
        rows.all = MagicMock(return_value=[("send_email", "require"), ("read_row", "auto")])
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=rows)

        gate = await AIService(mock_session)._build_policy_gate(cfg, str(COMPANY_ID))
        assert isinstance(gate, ToolPolicyGate)


class TestAIInvokeRouteValidation:
    """``POST /ai-invoke/run`` must require exactly one of agent_name / agent_id."""

    def _make_invoke_client(self):
        """Build a TestClient for /ai-invoke/run with auth + DB mocked."""
        from integration_hub_backend.api.api.deps import (
            AuthContext,
            CurrentUserPayload,
            get_db,
            require_any_auth,
        )
        from integration_hub_backend.api.api.routes.ai_invoke import router

        app = FastAPI()
        app.include_router(router)  # router already has prefix="/ai-invoke"

        user = CurrentUserPayload(
            user_id=USER_ID,
            company_id=COMPANY_ID,
            role="company_admin",
            email="admin@example.com",
        )
        auth_ctx = AuthContext(user=user, is_internal=False)
        mock_session = AsyncMock()
        # LLM budget gate reads the cap via execute().scalars().first(); default
        # to None (no cap) so the gate passes. Tests override execute as needed.
        _budget_result = MagicMock()
        _budget_result.scalars.return_value.first.return_value = None
        mock_session.execute = AsyncMock(return_value=_budget_result)

        async def _mock_db():
            yield mock_session

        app.dependency_overrides[require_any_auth] = lambda: auth_ctx
        app.dependency_overrides[get_db] = _mock_db
        return TestClient(app), mock_session

    def test_missing_both_returns_422(self):
        client, _ = self._make_invoke_client()
        resp = client.post(
            "/ai-invoke/run",
            json={"prompt": "hello"},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 422
        assert "must be provided" in resp.json()["detail"].lower()

    def test_both_provided_returns_422(self):
        client, _ = self._make_invoke_client()
        resp = client.post(
            "/ai-invoke/run",
            json={
                "prompt": "hello",
                "agent_name": "x",
                "agent_id": str(uuid.uuid4()),
            },
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 422
        assert "not both" in resp.json()["detail"].lower()

    def test_agent_id_path_calls_service_with_id(self):
        """When agent_id is supplied, AIService.complete is invoked with it."""

        client, _ = self._make_invoke_client()
        agent_id = uuid.uuid4()

        with patch("integration_hub_backend.api.api.routes.ai_invoke.AIService") as MockService:
            instance = MagicMock()
            instance.complete = AsyncMock(
                return_value={"data": {"x": 1}, "provider": "anthropic", "model": "m"}
            )
            MockService.return_value = instance

            resp = client.post(
                "/ai-invoke/run",
                json={"prompt": "hi", "agent_id": str(agent_id)},
                headers={"Authorization": "Bearer x"},
            )

        assert resp.status_code == 200
        # AIService.complete was called with agent_id, not agent_name
        instance.complete.assert_awaited_once()
        kwargs = instance.complete.call_args.kwargs
        assert kwargs["agent_id"] == agent_id
        assert kwargs["agent_name"] is None

    def test_agent_name_path_still_works(self):
        """Backward-compat: agent_name path unchanged."""
        client, _ = self._make_invoke_client()

        with patch("integration_hub_backend.api.api.routes.ai_invoke.AIService") as MockService:
            instance = MagicMock()
            instance.complete = AsyncMock(
                return_value={"data": {}, "provider": "anthropic", "model": "m"}
            )
            MockService.return_value = instance

            resp = client.post(
                "/ai-invoke/run",
                json={"prompt": "hi", "agent_name": "my-agent"},
                headers={"Authorization": "Bearer x"},
            )

        assert resp.status_code == 200
        kwargs = instance.complete.call_args.kwargs
        assert kwargs["agent_name"] == "my-agent"
        assert kwargs["agent_id"] is None
