from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from prometheus_telegram_bot.config import AccessControlConfig


logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class AccessRequest:
    chat_id: str
    display_name: str
    username: str | None
    requested_at: str


@dataclass(slots=True)
class AccessControlState:
    admin_chat_ids: set[str] = field(default_factory=set)
    allowed_chat_ids: set[str] = field(default_factory=set)
    pending_requests: dict[str, AccessRequest] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AccessDecision:
    status: str
    request: AccessRequest | None = None


class AccessControlService:
    def __init__(self, config: AccessControlConfig) -> None:
        self._config = config
        self._state_file = config.state_file
        self._state = self._load_state()
        self._merge_seed_ids()
        self._persist_state()
        logger.info(
            "Access control initialized with %s admin(s), %s allowed chat(s), %s pending request(s)",
            len(self._state.admin_chat_ids),
            len(self._state.allowed_chat_ids),
            len(self._state.pending_requests),
        )

    def is_allowed(self, chat_id: int | str | None) -> bool:
        if chat_id is None:
            return False
        return self._normalize_chat_id(chat_id) in self._state.allowed_chat_ids

    def is_admin(self, chat_id: int | str | None) -> bool:
        if chat_id is None:
            return False
        return self._normalize_chat_id(chat_id) in self._state.admin_chat_ids

    def allowed_chat_ids(self) -> list[str]:
        return sorted(self._state.allowed_chat_ids)

    def pending_requests(self) -> list[AccessRequest]:
        return sorted(
            self._state.pending_requests.values(),
            key=lambda item: item.requested_at,
        )

    def register_start_request(
        self,
        chat_id: int | str,
        *,
        display_name: str,
        username: str | None,
    ) -> AccessDecision:
        normalized_chat_id = self._normalize_chat_id(chat_id)

        if not self._state.admin_chat_ids:
            logger.info("Bootstrapping admin role for chat_id=%s", normalized_chat_id)
            request = self._grant_admin(
                normalized_chat_id,
                display_name=display_name,
                username=username,
            )
            return AccessDecision(status="bootstrap_admin", request=request)

        if normalized_chat_id in self._state.allowed_chat_ids:
            logger.info("Chat_id=%s is already allowed", normalized_chat_id)
            return AccessDecision(status="allowed")

        existing_request = self._state.pending_requests.get(normalized_chat_id)
        if existing_request is not None:
            logger.info("Pending request already exists for chat_id=%s", normalized_chat_id)
            return AccessDecision(status="pending", request=existing_request)

        request = AccessRequest(
            chat_id=normalized_chat_id,
            display_name=display_name,
            username=username,
            requested_at=datetime.now(tz=UTC).isoformat(),
        )
        self._state.pending_requests[normalized_chat_id] = request
        self._persist_state()
        logger.info("Registered access request for chat_id=%s", normalized_chat_id)
        return AccessDecision(status="requested", request=request)

    def approve(self, chat_id: int | str) -> AccessRequest | None:
        normalized_chat_id = self._normalize_chat_id(chat_id)
        request = self._state.pending_requests.pop(normalized_chat_id, None)
        if request is None:
            logger.warning("Approve requested for unknown chat_id=%s", normalized_chat_id)
            return None

        self._state.allowed_chat_ids.add(normalized_chat_id)
        self._persist_state()
        logger.info("Approved chat_id=%s", normalized_chat_id)
        return request

    def deny(self, chat_id: int | str) -> AccessRequest | None:
        normalized_chat_id = self._normalize_chat_id(chat_id)
        request = self._state.pending_requests.pop(normalized_chat_id, None)
        if request is None:
            logger.warning("Deny requested for unknown chat_id=%s", normalized_chat_id)
            return None

        self._persist_state()
        logger.info("Denied chat_id=%s", normalized_chat_id)
        return request

    def _grant_admin(
        self,
        normalized_chat_id: str,
        *,
        display_name: str,
        username: str | None,
    ) -> AccessRequest:
        self._state.admin_chat_ids.add(normalized_chat_id)
        self._state.allowed_chat_ids.add(normalized_chat_id)
        self._state.pending_requests.pop(normalized_chat_id, None)
        self._persist_state()
        return AccessRequest(
            chat_id=normalized_chat_id,
            display_name=display_name,
            username=username,
            requested_at=datetime.now(tz=UTC).isoformat(),
        )

    def _load_state(self) -> AccessControlState:
        if not self._state_file.exists():
            logger.info("No existing access-control state found at %s", self._state_file)
            return AccessControlState()

        logger.info("Loading access-control state from %s", self._state_file)
        raw_state = json.loads(self._state_file.read_text(encoding="utf-8"))
        pending_requests = {
            str(chat_id): AccessRequest(
                chat_id=str(chat_id),
                display_name=str(item.get("display_name", chat_id)),
                username=item.get("username"),
                requested_at=str(item.get("requested_at")),
            )
            for chat_id, item in raw_state.get("pending_requests", {}).items()
        }
        return AccessControlState(
            admin_chat_ids={str(item) for item in raw_state.get("admin_chat_ids", [])},
            allowed_chat_ids={str(item) for item in raw_state.get("allowed_chat_ids", [])},
            pending_requests=pending_requests,
        )

    def _merge_seed_ids(self) -> None:
        self._state.admin_chat_ids.update(
            self._normalize_chat_id(item) for item in self._config.admin_chat_ids
        )
        self._state.allowed_chat_ids.update(
            self._normalize_chat_id(item) for item in self._config.allowed_chat_ids
        )
        self._state.allowed_chat_ids.update(self._state.admin_chat_ids)
        logger.info(
            "Merged seeded access-control IDs: %s admin seed(s), %s allowed seed(s)",
            len(self._config.admin_chat_ids),
            len(self._config.allowed_chat_ids),
        )

    def _persist_state(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "admin_chat_ids": sorted(self._state.admin_chat_ids),
            "allowed_chat_ids": sorted(self._state.allowed_chat_ids),
            "pending_requests": {
                chat_id: asdict(request)
                for chat_id, request in sorted(self._state.pending_requests.items())
            },
        }

        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=self._state_file.parent,
            suffix=".tmp",
        ) as temp_file:
            json.dump(payload, temp_file, indent=2)
            temp_path = Path(temp_file.name)

        temp_path.replace(self._state_file)
        logger.debug("Persisted access-control state to %s", self._state_file)

    @staticmethod
    def _normalize_chat_id(chat_id: int | str) -> str:
        return str(chat_id)
