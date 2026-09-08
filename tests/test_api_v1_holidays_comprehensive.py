"""
Tests for services/api/v1/holidays.py
Covers:
- GET /
- GET /today
- GET /{year}
- POST / (add manual holiday, conflict, invalid date)
- DELETE /{date_str} (remove holiday, not found, invalid date)
- POST /sync (sync holidays from bist/kap)
- GET /audit/log
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.v1.holidays import router


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/holidays")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_list_holidays(client: TestClient) -> None:
    with patch("services.core.holiday_manager.holiday_manager") as mock_mgr:
        mock_mgr.get_holidays.return_value = {date(2026, 1, 1), date(2026, 4, 23)}
        mock_mgr.get_half_days.return_value = {date(2026, 10, 28)}
        mock_mgr.get_sudden_holidays.return_value = set()
        mock_mgr.get_holiday_name.side_effect = lambda d: "Yılbaşı" if d.month == 1 else "23 Nisan"

        resp = client.get("/api/v1/holidays/?year=2026")
        assert resp.status_code == 200
        data = resp.json()
        assert data["year"] == 2026
        assert data["total"] == 2
        assert len(data["holidays"]) == 2
        assert data["half_days"] == ["2026-10-28"]


def test_today_status(client: TestClient) -> None:
    with (
        patch("services.core.holiday_manager.holiday_manager") as mock_mgr,
        patch("services.core.market_calendar.get_market_calendar") as mock_cal_fn,
    ):
        mock_cal = MagicMock()
        mock_cal.is_trading_day.return_value = True
        mock_cal_fn.return_value = mock_cal

        mock_mgr.is_holiday.return_value = False
        mock_mgr.is_half_day.return_value = False

        resp = client.get("/api/v1/holidays/today")
        assert resp.status_code == 200
        data = resp.json()
        assert "date" in data
        assert data["is_holiday"] is False
        assert data["is_half_day"] is False
        assert data["is_trading_day"] is True
        assert data["name"] is None


def test_list_holidays_by_year(client: TestClient) -> None:
    with patch("services.core.holiday_manager.holiday_manager") as mock_mgr:
        mock_mgr.get_holidays.return_value = {date(2025, 5, 19)}
        mock_mgr.get_half_days.return_value = set()
        mock_mgr.get_sudden_holidays.return_value = set()
        mock_mgr.get_holiday_name.return_value = "19 Mayıs"

        resp = client.get("/api/v1/holidays/2025")
        assert resp.status_code == 200
        data = resp.json()
        assert data["year"] == 2025
        assert data["total"] == 1
        assert data["holidays"][0]["name"] == "19 Mayıs"


def test_add_holiday_success_and_conflict(client: TestClient) -> None:
    with patch("services.core.holiday_manager.holiday_manager") as mock_mgr:
        mock_mgr.is_holiday.side_effect = [False, True]
        mock_mgr.is_half_day.return_value = False
        mock_mgr.get_holiday_name.return_value = "Anlık BIST Tatili"

        # 1. Success
        resp = client.post(
            "/api/v1/holidays/",
            json={"date": "2026-11-05", "reason": "Özel Karar"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["date"] == "2026-11-05"
        assert data["source"] == "manual"
        mock_mgr.add_manual_holiday.assert_called_once()

        # 2. Conflict (already exists)
        resp_conflict = client.post(
            "/api/v1/holidays/",
            json={"date": "2026-11-05", "reason": "Özel Karar"},
        )
        assert resp_conflict.status_code == 409

        # 3. Invalid format
        resp_invalid = client.post(
            "/api/v1/holidays/",
            json={"date": "not-a-date", "reason": "Özel Karar"},
        )
        assert resp_invalid.status_code == 400


def test_remove_holiday_success_and_not_found(client: TestClient) -> None:
    with patch("services.core.holiday_manager.holiday_manager") as mock_mgr:
        mock_mgr.is_holiday.side_effect = [True, False]

        # 1. Success
        resp = client.delete("/api/v1/holidays/2026-11-05?reason=Iptal")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_mgr.remove_holiday.assert_called_once()

        # 2. Not found
        resp_nf = client.delete("/api/v1/holidays/2026-11-05?reason=Iptal")
        assert resp_nf.status_code == 404

        # 3. Invalid format
        resp_inv = client.delete("/api/v1/holidays/invalid-date")
        assert resp_inv.status_code == 400


def test_sync_holidays(client: TestClient) -> None:
    with patch("services.core.holiday_manager.holiday_manager") as mock_mgr:
        # BIST sync success
        mock_mgr.sync_from_bist = AsyncMock(return_value=True)
        mock_mgr.get_holidays.return_value = {date(2026, 1, 1)}

        resp = client.post("/api/v1/holidays/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["source"] == "BIST"

        # BIST fails, KAP finds holidays
        mock_mgr.sync_from_bist = AsyncMock(return_value=False)
        mock_mgr.check_kap_for_holidays = AsyncMock(return_value=["2026-10-29"])
        resp_kap = client.post("/api/v1/holidays/sync")
        assert resp_kap.status_code == 200
        assert resp_kap.json()["source"] == "KAP"


def test_audit_log(client: TestClient) -> None:
    with patch("services.core.holiday_manager.holiday_manager") as mock_mgr:
        mock_mgr.get_audit_log.return_value = [
            {"action": "ADD", "date": "2026-11-05", "reason": "Test", "timestamp": "2026-09-08T12:00:00"}
        ]

        resp = client.get("/api/v1/holidays/audit/log?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["entries"][0]["action"] == "ADD"
