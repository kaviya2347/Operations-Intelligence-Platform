"""Demo identities, roles and row-level security.

In production these come from the company identity provider (SSO). For the
demo, the dashboard sends X-OIP-User and the API applies the same rules the
Power BI report used: roles decide what pages and columns a person sees, and
row-level security decides which queues' rows reach them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from oip.reference import QUEUES


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str                 # Admin | Analyst | Team leader | Client viewer
    title: str
    queues: tuple | None      # None = all queues
    can_sql: bool
    can_see_agent_names: bool

    def public(self):
        d = asdict(self)
        d["queues"] = list(self.queues) if self.queues else None
        return d


USERS = {
    "ops-admin": User("ops-admin", "Operations Admin", "Admin", "Head of delivery", None, True, True),
    "analyst": User("analyst", "Data Analyst", "Analyst", "Data & AI team", None, True, True),
    "tl-billing": User("tl-billing", "Team Leader, Billing", "Team leader", "Northwind Billing (morning)", ("Q01",), False, True),
    "client-meridian": User("client-meridian", "Meridian Bank viewer", "Client viewer", "Client account team", ("Q04", "Q09"), False, False),
}
DEFAULT_USER = "ops-admin"


def get_user(user_id: str | None) -> User:
    return USERS.get(user_id or DEFAULT_USER, USERS[DEFAULT_USER])


def allowed_queues(user: User) -> list[str]:
    return list(user.queues) if user.queues else [q.queue_id for q in QUEUES]
