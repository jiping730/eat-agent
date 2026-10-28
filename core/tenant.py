"""Tenant context and role checks for the small-platform deployment.

The platform intentionally keeps tenancy in the application and database
instead of introducing a separate identity or policy service.  Every request
selects one tenant, and the service verifies that the authenticated user is an
active member before returning the context to downstream components.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from core.persistence import ConversationStore


class TenantAccessError(PermissionError):
    """Raised when a user selects a tenant they do not belong to."""


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role in {"owner", "admin"}


class TenantService:
    """Resolve tenant headers and enforce the minimal role model."""

    _slug_re = re.compile(r"^[a-z0-9][a-z0-9_-]{1,119}$")

    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    def resolve(self, user_id: str, requested_tenant_id: str | None = None) -> TenantContext:
        tenant_id = self.store.resolve_tenant_id(user_id, requested_tenant_id)
        membership = self.store.get_membership(tenant_id, user_id)
        tenant = self.store.get_tenant(tenant_id)
        if tenant is None or tenant.status != "active" or membership is None or membership.status != "active":
            raise TenantAccessError("当前用户不是该租户成员")
        return TenantContext(tenant_id=tenant_id, user_id=user_id, role=membership.role)

    def require_member(self, user_id: str, tenant_id: str) -> TenantContext:
        return self.resolve(user_id, tenant_id)

    def require_role(self, user_id: str, tenant_id: str, roles: set[str]) -> TenantContext:
        context = self.require_member(user_id, tenant_id)
        if context.role not in roles:
            raise TenantAccessError("当前租户角色没有执行该操作的权限")
        return context

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return self.store.list_user_tenants(user_id)

    def create(self, user_id: str, name: str, slug: str | None = None) -> dict[str, Any]:
        normalized_slug = self.store._tenant_slug(slug) if slug else f"tenant-{uuid.uuid4().hex[:16]}"
        if not self._slug_re.fullmatch(normalized_slug):
            raise ValueError("租户标识只能包含小写字母、数字、下划线和短横线，且长度为 2-120")
        return self.store.create_tenant(
            tenant_id=str(uuid.uuid4()), name=name, slug=normalized_slug, owner_id=user_id
        )

    @staticmethod
    def role_allows(role: str, operation: str) -> bool:
        if operation in {"view", "use"}:
            return role in {"owner", "admin", "member"}
        if operation in {"manage", "settings"}:
            return role in {"owner", "admin"}
        if operation == "delete":
            return role == "owner"
        return False

