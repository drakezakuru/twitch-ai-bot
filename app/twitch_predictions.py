"""Native Twitch Prediction creation for the authenticated panel."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends

from app.security import auth_dependency
from app.twitch_polls import _broadcaster_and_headers


router = APIRouter(dependencies=[Depends(auth_dependency)])


def _normalize_prediction(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "title": data.get("title", ""),
        "status": data.get("status", ""),
        "winning_outcome_id": data.get("winning_outcome_id"),
        "prediction_window": data.get("prediction_window", 0),
        "created_at": data.get("created_at", ""),
        "outcomes": [
            {
                "id": outcome.get("id"),
                "title": outcome.get("title", ""),
                "color": outcome.get("color", ""),
                "users": int(outcome.get("users") or 0),
                "channel_points": int(outcome.get("channel_points") or 0),
            }
            for outcome in (data.get("outcomes") or [])
            if isinstance(outcome, dict)
        ],
    }


def _helix_error(status_code: int) -> str:
    if status_code == 401:
        return "invalid_token"
    if status_code == 403:
        return "helix_forbidden"
    if status_code == 429:
        return "rate_limited"
    return f"helix_{status_code}"


async def get_active_prediction(account_id: int, channel: str) -> dict[str, Any]:
    """Return the current ACTIVE or LOCKED prediction for one exact scope."""
    broadcaster_id, headers, _, error = await _broadcaster_and_headers(
        account_id, channel, {"channel:manage:predictions"},
    )
    if not broadcaster_id or not headers:
        return {"error": error}

    from app.twitch_helix import HELIX_BASE

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{HELIX_BASE}/predictions",
                headers=headers,
                params={"broadcaster_id": broadcaster_id, "first": 25},
            )
    except Exception:
        return {"error": "request_failed"}
    if response.status_code != 200:
        return {"error": _helix_error(response.status_code)}
    data = response.json().get("data") or []
    current = next(
        (item for item in data if item.get("status") in {"ACTIVE", "LOCKED"}), None,
    )
    return {"ok": True, "prediction": _normalize_prediction(current) if current else None}


async def end_prediction(
    account_id: int,
    channel: str,
    prediction_id: str,
    status: str,
    *,
    winning_outcome_id: str | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Safely advance the current exact-scope prediction lifecycle once."""
    status = str(status or "").upper()
    prediction_id = str(prediction_id or "").strip()
    if status not in {"LOCKED", "RESOLVED", "CANCELED"}:
        return {"error": "invalid_prediction_status"}
    if not prediction_id:
        return {"error": "prediction_id_required"}
    if status == "CANCELED" and confirmed is not True:
        return {"error": "confirmation_required"}

    current_result = await get_active_prediction(account_id, channel)
    if not current_result.get("ok"):
        return {"error": current_result.get("error", "request_failed")}
    prediction = current_result.get("prediction")
    if not prediction or prediction.get("id") != prediction_id:
        return {"error": "no_matching_active_prediction"}
    current_status = prediction.get("status")
    if status == "LOCKED" and current_status != "ACTIVE":
        return {"error": "prediction_not_active"}
    if status == "RESOLVED":
        winning_outcome_id = str(winning_outcome_id or "").strip()
        if current_status != "LOCKED":
            return {"error": "prediction_not_locked"}
        if not winning_outcome_id:
            return {"error": "winning_outcome_required"}
        if winning_outcome_id not in {str(outcome.get("id")) for outcome in prediction["outcomes"]}:
            return {"error": "winning_outcome_invalid"}

    broadcaster_id, headers, _, error = await _broadcaster_and_headers(
        account_id, channel, {"channel:manage:predictions"},
    )
    if not broadcaster_id or not headers:
        return {"error": error}
    payload: dict[str, str] = {
        "broadcaster_id": broadcaster_id,
        "id": prediction_id,
        "status": status,
    }
    if status == "RESOLVED":
        payload["winning_outcome_id"] = winning_outcome_id

    from app.twitch_helix import HELIX_BASE

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(f"{HELIX_BASE}/predictions", headers=headers, json=payload)
    except Exception:
        return {"error": "request_failed"}
    if response.status_code != 200:
        return {"error": _helix_error(response.status_code)}
    data = response.json().get("data") or []
    return {"ok": True, "prediction": _normalize_prediction(data[0]) if data else None}


async def create_prediction(
    account_id: int, channel: str, title: str, outcomes: list[Any], prediction_window: int = 120,
) -> dict[str, Any]:
    """Create one broadcaster-owned Prediction through Twitch Helix."""
    title = str(title or "").strip()[:60]
    normalized_outcomes = [str(outcome).strip()[:25] for outcome in outcomes if str(outcome).strip()]
    if not title or not 2 <= len(normalized_outcomes) <= 10:
        return {"error": "title_and_2_to_10_outcomes_required"}
    try:
        prediction_window = int(prediction_window)
    except (TypeError, ValueError):
        return {"error": "invalid_prediction_window"}
    if not 30 <= prediction_window <= 1800:
        return {"error": "invalid_prediction_window"}

    broadcaster_id, headers, _, error = await _broadcaster_and_headers(
        account_id, channel, {"channel:manage:predictions"},
    )
    if not broadcaster_id or not headers:
        return {"error": error}

    from app.twitch_helix import HELIX_BASE

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{HELIX_BASE}/predictions",
                headers=headers,
                json={
                    "broadcaster_id": broadcaster_id,
                    "title": title,
                    "outcomes": [{"title": outcome} for outcome in normalized_outcomes],
                    "prediction_window": prediction_window,
                },
            )
    except Exception:
        return {"error": "request_failed"}

    if response.status_code == 200:
        data = response.json().get("data") or []
        return {"ok": True, "prediction": _normalize_prediction(data[0]) if data else None}
    return {"error": _helix_error(response.status_code)}


@router.post("/api/widgets/twitch-prediction")
async def create_prediction_route(data: dict[str, Any]) -> dict[str, Any]:
    outcomes = data.get("outcomes")
    if not isinstance(outcomes, list):
        return {"error": "title_and_2_to_10_outcomes_required"}
    try:
        account_id = int(data.get("account_id") or 0)
    except (TypeError, ValueError):
        return {"error": "account_and_channel_required"}
    return await create_prediction(
        account_id=account_id,
        channel=str(data.get("channel") or ""),
        title=str(data.get("title") or ""),
        outcomes=outcomes,
        prediction_window=data.get("prediction_window", 120),
    )


@router.post("/api/widgets/twitch-prediction/active")
async def active_prediction_route(data: dict[str, Any]) -> dict[str, Any]:
    try:
        account_id = int(data.get("account_id") or 0)
    except (TypeError, ValueError):
        return {"error": "account_and_channel_required"}
    return await get_active_prediction(account_id, str(data.get("channel") or ""))


@router.post("/api/widgets/twitch-prediction/end")
async def end_prediction_route(data: dict[str, Any]) -> dict[str, Any]:
    try:
        account_id = int(data.get("account_id") or 0)
    except (TypeError, ValueError):
        return {"error": "account_and_channel_required"}
    return await end_prediction(
        account_id,
        str(data.get("channel") or ""),
        str(data.get("prediction_id") or ""),
        str(data.get("status") or ""),
        winning_outcome_id=data.get("winning_outcome_id"),
        confirmed=data.get("confirmed") is True,
    )
