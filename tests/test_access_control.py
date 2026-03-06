from __future__ import annotations

import json
from pathlib import Path

from prometheus_telegram_bot.access_control import AccessControlService
from prometheus_telegram_bot.config import AccessControlConfig


def test_first_start_bootstraps_admin(tmp_path: Path) -> None:
    state_file = tmp_path / "access-control.json"
    service = AccessControlService(AccessControlConfig(state_file=state_file))

    decision = service.register_start_request(
        123,
        display_name="First User",
        username="first",
    )

    assert decision.status == "bootstrap_admin"
    assert service.is_admin(123)
    assert service.is_allowed(123)
    assert state_file.exists()


def test_request_requires_admin_approval(tmp_path: Path) -> None:
    state_file = tmp_path / "access-control.json"
    service = AccessControlService(AccessControlConfig(state_file=state_file))

    service.register_start_request(1, display_name="Admin", username="admin")
    request_decision = service.register_start_request(
        2,
        display_name="Second User",
        username="second",
    )

    assert request_decision.status == "requested"
    assert not service.is_allowed(2)
    assert len(service.pending_requests()) == 1

    approved_request = service.approve(2)

    assert approved_request is not None
    assert approved_request.chat_id == "2"
    assert service.is_allowed(2)
    assert not service.is_admin(2)
    assert service.pending_requests() == []


def test_seeded_admins_are_persisted(tmp_path: Path) -> None:
    state_file = tmp_path / "access-control.json"
    config = AccessControlConfig(
        state_file=state_file,
        admin_chat_ids=["10"],
        allowed_chat_ids=["20"],
    )

    service = AccessControlService(config)

    assert service.is_admin("10")
    assert service.is_allowed("10")
    assert service.is_allowed("20")


def test_denied_request_can_be_requested_again(tmp_path: Path) -> None:
    state_file = tmp_path / "access-control.json"
    service = AccessControlService(AccessControlConfig(state_file=state_file))

    service.register_start_request(1, display_name="Admin", username="admin")
    first_request = service.register_start_request(
        2,
        display_name="Denied User",
        username="denied",
    )
    denied_request = service.deny(2)
    second_request = service.register_start_request(
        2,
        display_name="Denied User",
        username="denied",
    )

    assert first_request.status == "requested"
    assert denied_request is not None
    assert denied_request.chat_id == "2"
    assert second_request.status == "requested"
    assert len(service.pending_requests()) == 1


def test_persisted_state_is_loaded_on_restart(tmp_path: Path) -> None:
    state_file = tmp_path / "access-control.json"
    service = AccessControlService(AccessControlConfig(state_file=state_file))

    service.register_start_request(1, display_name="Admin", username="admin")
    service.register_start_request(2, display_name="User", username="user")
    service.approve(2)

    reloaded_service = AccessControlService(AccessControlConfig(state_file=state_file))

    assert reloaded_service.is_admin(1)
    assert reloaded_service.is_allowed(2)
    assert reloaded_service.pending_requests() == []


def test_pending_requests_are_persisted_to_state_file(tmp_path: Path) -> None:
    state_file = tmp_path / "access-control.json"
    service = AccessControlService(AccessControlConfig(state_file=state_file))

    service.register_start_request(1, display_name="Admin", username="admin")
    service.register_start_request(2, display_name="Pending User", username="pending")

    persisted = json.loads(state_file.read_text(encoding="utf-8"))

    assert persisted["admin_chat_ids"] == ["1"]
    assert persisted["allowed_chat_ids"] == ["1"]
    assert "2" in persisted["pending_requests"]
