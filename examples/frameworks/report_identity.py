"""Application-owned adapter for an async identity service and sync entitlement DB."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypedDict

from cedarpy_web import Facts, Session


class StepUpStatus(TypedDict):
    user_id: str
    session_id: str
    stepped_up: bool


class AuthServiceClient(Protocol):
    async def verify_token(self, token: str) -> Session | None: ...

    async def step_up_status(
        self, *, user_id: str, session_id: str
    ) -> StepUpStatus: ...


@dataclass(frozen=True)
class ReportIdentity:
    auth: AuthServiceClient
    can_export: Callable[[str], bool]

    async def verify_token(self, token: str) -> Session | None:
        try:
            session = await self.auth.verify_token(token)
        except (OSError, ValueError):
            return None
        return session if isinstance(session, Session) else None

    async def is_stepped_up(self, session: Session) -> bool:
        try:
            status = await self.auth.step_up_status(
                user_id=session.user_id, session_id=session.session_id
            )
        except (OSError, ValueError):
            return False
        match status:
            case {"user_id": user_id, "session_id": session_id, "stepped_up": True}:
                return user_id == session.user_id and session_id == session.session_id
            case _:
                return False

    async def export_facts(self, session: Session) -> Facts:
        can_export = await asyncio.to_thread(self.can_export, session.user_id)
        stepped_up = await self.is_stepped_up(session)
        return Facts(
            principal_attrs={"can_export": can_export},
            context={"stepped_up": stepped_up},
        )
