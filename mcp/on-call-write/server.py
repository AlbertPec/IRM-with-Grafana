import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("grafana-oncall-write")


ONCALL_API_URL = os.environ["GRAFANA_ONCALL_API_URL"].rstrip("/")
ONCALL_API_TOKEN = os.environ["GRAFANA_ONCALL_API_TOKEN"]
GRAFANA_URL = os.environ.get("GRAFANA_URL", "").rstrip("/")
GRAFANA_STACK_URL = os.environ.get("GRAFANA_STACK_URL", GRAFANA_URL).rstrip("/")


def _headers() -> Dict[str, str]:
    headers = {
        "Authorization": ONCALL_API_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if GRAFANA_STACK_URL:
        headers["X-Grafana-URL"] = GRAFANA_STACK_URL
        headers["X-Grafana-Url"] = GRAFANA_STACK_URL

    return headers


async def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
) -> Any:
    url = f"{ONCALL_API_URL}{path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method=method,
            url=url,
            headers=_headers(),
            params=params,
            json=json,
        )

    try:
        payload = response.json()
    except Exception:
        payload = response.text

    if response.status_code >= 400:
        raise RuntimeError(
            {
                "status_code": response.status_code,
                "url": url,
                "response": payload,
            }
        )

    return payload


async def _get_all_pages(
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    params = dict(params or {})
    results: List[Dict[str, Any]] = []
    next_url: Optional[str] = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            if next_url:
                response = await client.get(next_url, headers=_headers())
            else:
                response = await client.get(
                    f"{ONCALL_API_URL}{path}",
                    headers=_headers(),
                    params=params,
                )

            try:
                payload = response.json()
            except Exception:
                payload = response.text

            if response.status_code >= 400:
                raise RuntimeError(
                    {
                        "status_code": response.status_code,
                        "url": str(response.url),
                        "response": payload,
                    }
                )

            if isinstance(payload, dict) and "results" in payload:
                results.extend(payload.get("results") or [])
                next_url = payload.get("next")

                if not next_url:
                    return results

                continue

            if isinstance(payload, list):
                return payload

            return [payload]


def _clean_shift_payload(shift: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a safe PUT payload for /api/v1/on_call_shifts/<id>/.

    The API may reject calculated/read-only fields, so remove them.
    """
    payload = dict(shift)

    for key in [
        "id",
        "created_at",
        "updated_at",
        "schedule",
        "schedule_name",
        "rolling_users",
    ]:
        payload.pop(key, None)

    return payload


def _clean_schedule_payload(schedule: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a safe PUT payload for /api/v1/schedules/<id>/.

    The API may reject calculated/read-only fields, so remove them.
    """
    payload = dict(schedule)

    for key in [
        "id",
        "on_call_now",
        "ical_url_export",
        "ical_url_export_overrides",
        "created_at",
        "updated_at",
        "current_shifts",
        "final_shifts",
    ]:
        payload.pop(key, None)

    return payload


def _replace_user_in_list(
    users: List[str],
    old_user_id: str,
    new_user_id: str,
) -> List[str]:
    """
    Replace old_user_id with new_user_id while preventing duplicates.
    """
    replaced: List[str] = []

    for user_id in users:
        replacement = new_user_id if user_id == old_user_id else user_id

        if replacement not in replaced:
            replaced.append(replacement)

    return replaced


def _swap_users_in_list(
    users: List[str],
    user_a_id: str,
    user_b_id: str,
) -> List[str]:
    """
    Swap user_a_id and user_b_id wherever they appear in a users list.
    """
    swapped: List[str] = []

    for user_id in users:
        if user_id == user_a_id:
            replacement = user_b_id
        elif user_id == user_b_id:
            replacement = user_a_id
        else:
            replacement = user_id

        if replacement not in swapped:
            swapped.append(replacement)

    return swapped


def _to_utc_z_string(dt: datetime) -> str:
    """
    Convert datetime to ISO UTC string with Z suffix.
    """
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_local_datetime(value: str, timezone_name: str) -> datetime:
    tz = ZoneInfo(timezone_name)
    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)

    return parsed.astimezone(tz)


def _local_day_range_to_utc_z_strings(
    date_yyyy_mm_dd: str,
    timezone_name: str,
) -> tuple[str, str]:
    tz = ZoneInfo(timezone_name)

    start_local = datetime.fromisoformat(date_yyyy_mm_dd).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
        tzinfo=tz,
    )

    end_local = start_local + timedelta(days=1)

    return _to_utc_z_string(start_local), _to_utc_z_string(end_local)


def _local_range_to_utc_z_strings(
    start_local: str,
    end_local: str,
    timezone_name: str,
) -> tuple[str, str]:
    start_dt_local = _parse_local_datetime(start_local, timezone_name)
    end_dt_local = _parse_local_datetime(end_local, timezone_name)

    if end_dt_local <= start_dt_local:
        raise ValueError("end_local must be later than start_local")

    return _to_utc_z_string(start_dt_local), _to_utc_z_string(end_dt_local)


@mcp.tool()
async def list_oncall_users(search: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List OnCall/IRM users. Use this to find user IDs by username, email, name, or ID.
    """
    users = await _get_all_pages("/api/v1/users/")

    if not search:
        return users

    needle = search.lower()

    return [
        user
        for user in users
        if needle in str(user.get("username", "")).lower()
        or needle in str(user.get("email", "")).lower()
        or needle in str(user.get("name", "")).lower()
        or needle in str(user.get("display_name", "")).lower()
        or needle in str(user.get("id", "")).lower()
        or needle in str(user.get("pk", "")).lower()
    ]


@mcp.tool()
async def list_oncall_schedules(name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List IRM/OnCall schedules.
    """
    params: Dict[str, Any] = {}

    if name:
        params["name"] = name

    return await _get_all_pages("/api/v1/schedules/", params=params)


@mcp.tool()
async def get_oncall_schedule(schedule_id: str) -> Dict[str, Any]:
    """
    Get one IRM/OnCall schedule by ID.
    """
    return await _request("GET", f"/api/v1/schedules/{schedule_id}/")


@mcp.tool()
async def get_oncall_schedule_current_oncall(schedule_id: str) -> Dict[str, Any]:
    """
    Get current on-call users for a schedule.
    """
    return await _request("GET", f"/api/v1/schedules/{schedule_id}/current_oncall/")


@mcp.tool()
async def list_oncall_shifts(
    schedule_id: Optional[str] = None,
    name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List IRM/OnCall shifts. Optionally filter by schedule_id or exact shift name.
    """
    params: Dict[str, Any] = {}

    if schedule_id:
        params["schedule_id"] = schedule_id

    if name:
        params["name"] = name

    return await _get_all_pages("/api/v1/on_call_shifts/", params=params)


@mcp.tool()
async def get_oncall_shift(shift_id: str) -> Dict[str, Any]:
    """
    Get one IRM/OnCall shift by ID.
    """
    return await _request("GET", f"/api/v1/on_call_shifts/{shift_id}/")


@mcp.tool()
async def update_oncall_shift_users(
    shift_id: str,
    users: List[str],
) -> Dict[str, Any]:
    """
    Replace the users array on an existing IRM/OnCall shift.

    This preserves all other fields returned by the API and only changes users.
    """
    shift = await get_oncall_shift(shift_id)

    payload = _clean_shift_payload(shift)
    payload["users"] = users

    updated = await _request(
        "PUT",
        f"/api/v1/on_call_shifts/{shift_id}/",
        json=payload,
    )

    verify = await get_oncall_shift(shift_id)
    persisted_users = list(verify.get("users") or [])

    return {
        "changed": persisted_users == users,
        "shift_id": shift_id,
        "requested_users": users,
        "persisted_users": persisted_users,
        "updated_shift_response": updated,
        "verified_shift": verify,
    }


@mcp.tool()
async def replace_user_in_oncall_shift(
    shift_id: str,
    old_user_id: str,
    new_user_id: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Replace one user with another in a single IRM/OnCall shift.

    By default dry_run=True, so it only reports what would change.
    """
    shift = await get_oncall_shift(shift_id)
    current_users = list(shift.get("users") or [])

    if old_user_id not in current_users:
        return {
            "dry_run": dry_run,
            "changed": False,
            "reason": "old_user_id_not_present",
            "shift_id": shift_id,
            "shift_name": shift.get("name"),
            "current_users": current_users,
        }

    new_users = _replace_user_in_list(
        users=current_users,
        old_user_id=old_user_id,
        new_user_id=new_user_id,
    )

    if dry_run:
        return {
            "dry_run": True,
            "changed": current_users != new_users,
            "shift_id": shift_id,
            "shift_name": shift.get("name"),
            "old_user_id": old_user_id,
            "new_user_id": new_user_id,
            "previous_users": current_users,
            "new_users": new_users,
        }

    updated = await update_oncall_shift_users(
        shift_id=shift_id,
        users=new_users,
    )

    return {
        "dry_run": False,
        "changed": updated.get("changed", False),
        "shift_id": shift_id,
        "shift_name": shift.get("name"),
        "old_user_id": old_user_id,
        "new_user_id": new_user_id,
        "previous_users": current_users,
        "new_users": new_users,
        "updated": updated,
    }


@mcp.tool()
async def replace_user_in_all_oncall_shifts(
    old_user_id: str,
    new_user_id: str,
    schedule_id: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Replace one OnCall/IRM user with another in every matching shift.

    By default dry_run=True, so it only reports what would change.
    Set dry_run=False to actually update shifts.
    """
    shifts = await list_oncall_shifts(schedule_id=schedule_id)

    matching = [
        shift
        for shift in shifts
        if old_user_id in list(shift.get("users") or [])
    ]

    planned = []
    changed = []

    for shift in matching:
        shift_id = shift["id"]
        current_users = list(shift.get("users") or [])

        new_users = _replace_user_in_list(
            users=current_users,
            old_user_id=old_user_id,
            new_user_id=new_user_id,
        )

        item = {
            "shift_id": shift_id,
            "shift_name": shift.get("name"),
            "schedule_id": shift.get("schedule_id"),
            "previous_users": current_users,
            "new_users": new_users,
        }

        planned.append(item)

        if not dry_run:
            updated = await update_oncall_shift_users(
                shift_id=shift_id,
                users=new_users,
            )

            changed.append(
                {
                    **item,
                    "updated": updated,
                }
            )

    return {
        "dry_run": dry_run,
        "old_user_id": old_user_id,
        "new_user_id": new_user_id,
        "schedule_id": schedule_id,
        "matching_count": len(matching),
        "planned": planned,
        "changed": changed,
    }


@mcp.tool()
async def propose_user_swap_in_oncall_shifts(
    user_a_id: str,
    user_b_id: str,
    schedule_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Propose a direct user swap across matching OnCall shifts.

    This does not write anything. It only shows which shifts would change.

    This changes rotation/layer membership, not a one-day swap request.
    """
    shifts = await list_oncall_shifts(schedule_id=schedule_id)

    planned = []

    for shift in shifts:
        current_users = list(shift.get("users") or [])

        contains_a = user_a_id in current_users
        contains_b = user_b_id in current_users

        if not contains_a and not contains_b:
            continue

        new_users = _swap_users_in_list(
            users=current_users,
            user_a_id=user_a_id,
            user_b_id=user_b_id,
        )

        planned.append(
            {
                "shift_id": shift.get("id"),
                "shift_name": shift.get("name"),
                "schedule_id": shift.get("schedule_id"),
                "contains_user_a": contains_a,
                "contains_user_b": contains_b,
                "previous_users": current_users,
                "new_users": new_users,
                "would_change": current_users != new_users,
            }
        )

    return {
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "schedule_id": schedule_id,
        "matching_count": len(planned),
        "planned": planned,
    }


@mcp.tool()
async def swap_users_in_oncall_shift(
    shift_id: str,
    user_a_id: str,
    user_b_id: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Swap two users inside one OnCall shift.

    Use this when both users are part of the same shift/layer.
    By default dry_run=True.
    """
    shift = await get_oncall_shift(shift_id)
    current_users = list(shift.get("users") or [])

    contains_a = user_a_id in current_users
    contains_b = user_b_id in current_users

    if not contains_a and not contains_b:
        return {
            "dry_run": dry_run,
            "changed": False,
            "reason": "neither_user_present",
            "shift_id": shift_id,
            "shift_name": shift.get("name"),
            "current_users": current_users,
        }

    new_users = _swap_users_in_list(
        users=current_users,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
    )

    if dry_run:
        return {
            "dry_run": True,
            "changed": current_users != new_users,
            "shift_id": shift_id,
            "shift_name": shift.get("name"),
            "user_a_id": user_a_id,
            "user_b_id": user_b_id,
            "contains_user_a": contains_a,
            "contains_user_b": contains_b,
            "previous_users": current_users,
            "new_users": new_users,
        }

    updated = await update_oncall_shift_users(
        shift_id=shift_id,
        users=new_users,
    )

    return {
        "dry_run": False,
        "changed": updated.get("changed", False),
        "shift_id": shift_id,
        "shift_name": shift.get("name"),
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "contains_user_a": contains_a,
        "contains_user_b": contains_b,
        "previous_users": current_users,
        "new_users": new_users,
        "updated": updated,
    }


@mcp.tool()
async def swap_users_in_all_oncall_shifts(
    user_a_id: str,
    user_b_id: str,
    schedule_id: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Swap two users across every matching OnCall shift.

    By default dry_run=True.

    This changes rotation/layer membership, not a one-day swap request.
    """
    shifts = await list_oncall_shifts(schedule_id=schedule_id)

    planned = []
    changed = []

    for shift in shifts:
        shift_id = shift["id"]
        current_users = list(shift.get("users") or [])

        contains_a = user_a_id in current_users
        contains_b = user_b_id in current_users

        if not contains_a and not contains_b:
            continue

        new_users = _swap_users_in_list(
            users=current_users,
            user_a_id=user_a_id,
            user_b_id=user_b_id,
        )

        item = {
            "shift_id": shift_id,
            "shift_name": shift.get("name"),
            "schedule_id": shift.get("schedule_id"),
            "contains_user_a": contains_a,
            "contains_user_b": contains_b,
            "previous_users": current_users,
            "new_users": new_users,
            "would_change": current_users != new_users,
        }

        planned.append(item)

        if not dry_run and current_users != new_users:
            updated = await update_oncall_shift_users(
                shift_id=shift_id,
                users=new_users,
            )

            changed.append(
                {
                    **item,
                    "updated": updated,
                }
            )

    return {
        "dry_run": dry_run,
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "schedule_id": schedule_id,
        "matching_count": len(planned),
        "planned": planned,
        "changed": changed,
    }


@mcp.tool()
async def swap_users_between_two_oncall_shifts(
    shift_a_id: str,
    user_a_id: str,
    shift_b_id: str,
    user_b_id: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Swap user_a from shift A with user_b from shift B.

    Use this when two people are in different shifts/layers and you want them
    to trade places.

    If shift_a_id == shift_b_id, this behaves like swap_users_in_oncall_shift.
    """
    if shift_a_id == shift_b_id:
        return await swap_users_in_oncall_shift(
            shift_id=shift_a_id,
            user_a_id=user_a_id,
            user_b_id=user_b_id,
            dry_run=dry_run,
        )

    shift_a = await get_oncall_shift(shift_a_id)
    shift_b = await get_oncall_shift(shift_b_id)

    users_a = list(shift_a.get("users") or [])
    users_b = list(shift_b.get("users") or [])

    if user_a_id not in users_a:
        return {
            "dry_run": dry_run,
            "changed": False,
            "reason": "user_a_not_present_in_shift_a",
            "shift_a_id": shift_a_id,
            "user_a_id": user_a_id,
            "shift_a_users": users_a,
        }

    if user_b_id not in users_b:
        return {
            "dry_run": dry_run,
            "changed": False,
            "reason": "user_b_not_present_in_shift_b",
            "shift_b_id": shift_b_id,
            "user_b_id": user_b_id,
            "shift_b_users": users_b,
        }

    new_users_a = _replace_user_in_list(
        users=users_a,
        old_user_id=user_a_id,
        new_user_id=user_b_id,
    )

    new_users_b = _replace_user_in_list(
        users=users_b,
        old_user_id=user_b_id,
        new_user_id=user_a_id,
    )

    plan = {
        "shift_a": {
            "shift_id": shift_a_id,
            "shift_name": shift_a.get("name"),
            "previous_users": users_a,
            "new_users": new_users_a,
        },
        "shift_b": {
            "shift_id": shift_b_id,
            "shift_name": shift_b.get("name"),
            "previous_users": users_b,
            "new_users": new_users_b,
        },
    }

    if dry_run:
        return {
            "dry_run": True,
            "changed": users_a != new_users_a or users_b != new_users_b,
            "user_a_id": user_a_id,
            "user_b_id": user_b_id,
            "plan": plan,
        }

    updated_a = await update_oncall_shift_users(
        shift_id=shift_a_id,
        users=new_users_a,
    )

    updated_b = await update_oncall_shift_users(
        shift_id=shift_b_id,
        users=new_users_b,
    )

    return {
        "dry_run": False,
        "changed": updated_a.get("changed", False) and updated_b.get("changed", False),
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "plan": plan,
        "updated_a": updated_a,
        "updated_b": updated_b,
    }


@mcp.tool()
async def update_oncall_schedule_shifts(
    schedule_id: str,
    shifts: List[str],
) -> Dict[str, Any]:
    """
    Replace the shift list attached to a schedule.

    This is used for normal schedule/layer management.
    """
    schedule = await get_oncall_schedule(schedule_id)

    payload = _clean_schedule_payload(schedule)
    payload["shifts"] = shifts

    updated = await _request(
        "PUT",
        f"/api/v1/schedules/{schedule_id}/",
        json=payload,
    )

    verify = await get_oncall_schedule(schedule_id)
    persisted_shifts = list(verify.get("shifts") or [])

    return {
        "changed": persisted_shifts == shifts,
        "schedule_id": schedule_id,
        "requested_shifts": shifts,
        "persisted_shifts": persisted_shifts,
        "updated_schedule_response": updated,
        "verified_schedule": verify,
    }


@mcp.tool()
async def attach_shift_to_oncall_schedule(
    schedule_id: str,
    shift_id: str,
) -> Dict[str, Any]:
    """
    Attach an existing shift to a schedule by appending its ID to schedule.shifts.
    """
    schedule = await get_oncall_schedule(schedule_id)
    current_shifts = list(schedule.get("shifts") or [])

    if shift_id in current_shifts:
        return {
            "changed": False,
            "reason": "shift_already_attached",
            "schedule_id": schedule_id,
            "shift_id": shift_id,
            "shifts": current_shifts,
        }

    new_shifts = current_shifts + [shift_id]

    updated = await update_oncall_schedule_shifts(
        schedule_id=schedule_id,
        shifts=new_shifts,
    )

    return {
        "changed": updated.get("changed", False),
        "schedule_id": schedule_id,
        "shift_id": shift_id,
        "previous_shifts": current_shifts,
        "new_shifts": new_shifts,
        "updated": updated,
    }


@mcp.tool()
async def detach_shift_from_oncall_schedule(
    schedule_id: str,
    shift_id: str,
) -> Dict[str, Any]:
    """
    Detach an existing shift from a schedule by removing its ID from schedule.shifts.

    This does not delete the shift object itself.
    """
    schedule = await get_oncall_schedule(schedule_id)
    current_shifts = list(schedule.get("shifts") or [])

    if shift_id not in current_shifts:
        return {
            "changed": False,
            "reason": "shift_not_attached",
            "schedule_id": schedule_id,
            "shift_id": shift_id,
            "shifts": current_shifts,
        }

    new_shifts = [item for item in current_shifts if item != shift_id]

    updated = await update_oncall_schedule_shifts(
        schedule_id=schedule_id,
        shifts=new_shifts,
    )

    return {
        "changed": updated.get("changed", False),
        "schedule_id": schedule_id,
        "shift_id": shift_id,
        "previous_shifts": current_shifts,
        "new_shifts": new_shifts,
        "updated": updated,
    }


@mcp.tool()
async def list_shift_swap_requests(
    schedule_id: Optional[str] = None,
    beneficiary: Optional[str] = None,
    benefactor: Optional[str] = None,
    open_only: Optional[bool] = None,
    starting_after: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List shift swap requests.

    Optional filters:
    - schedule_id: exact schedule ID.
    - beneficiary: user requesting coverage.
    - benefactor: user taking the shift.
    - open_only: true to show active untaken requests only.
    - starting_after: ISO timestamp string.
    """
    params: Dict[str, Any] = {}

    if schedule_id:
        params["schedule_id"] = schedule_id

    if beneficiary:
        params["beneficiary"] = beneficiary

    if benefactor:
        params["benefactor"] = benefactor

    if open_only is not None:
        params["open_only"] = str(open_only).lower()

    if starting_after:
        params["starting_after"] = starting_after

    return await _get_all_pages("/api/v1/shift_swaps/", params=params)


@mcp.tool()
async def get_shift_swap_request(
    shift_swap_id: str,
) -> Dict[str, Any]:
    """
    Get one shift swap request by ID.
    """
    return await _request("GET", f"/api/v1/shift_swaps/{shift_swap_id}/")


@mcp.tool()
async def create_shift_swap_request(
    schedule_id: str,
    beneficiary_user_id: str,
    swap_start: str,
    swap_end: str,
    description: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Create a shift swap request.

    This creates a request that beneficiary_user_id wants someone to cover
    their shifts in the given time range.

    Args:
        schedule_id: Schedule ID.
        beneficiary_user_id: User requesting coverage.
        swap_start: UTC ISO timestamp, e.g. 2026-05-23T00:00:00Z.
        swap_end: UTC ISO timestamp, e.g. 2026-05-24T00:00:00Z.
        description: Optional message.
        dry_run: If true, only reports payload.
    """
    payload: Dict[str, Any] = {
        "schedule": schedule_id,
        "swap_start": swap_start,
        "swap_end": swap_end,
        "beneficiary": beneficiary_user_id,
    }

    if description:
        payload["description"] = description

    if dry_run:
        return {
            "dry_run": True,
            "payload": payload,
        }

    created = await _request(
        "POST",
        "/api/v1/shift_swaps/",
        json=payload,
    )

    created_id = created.get("id")

    verification: Dict[str, Any] = {
        "verified": False,
        "reason": "created_response_has_no_id",
    }

    if created_id:
        try:
            read_back = await get_shift_swap_request(created_id)
            verification = {
                "verified": read_back.get("id") == created_id,
                "read_back": read_back,
            }
        except Exception as exc:
            verification = {
                "verified": False,
                "reason": "read_back_failed",
                "error": str(exc),
            }

    return {
        "dry_run": False,
        "created_shift_swap": created,
        "verification": verification,
    }


@mcp.tool()
async def create_shift_swap_request_for_local_day(
    schedule_id: str,
    beneficiary_user_id: str,
    date_yyyy_mm_dd: str,
    timezone_name: str = "Europe/Warsaw",
    description: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Create a shift swap request for one local calendar day.

    Example:
        date_yyyy_mm_dd = "2026-05-23"
        timezone_name = "Europe/Warsaw"

    The local midnight-to-midnight range is converted to UTC Z timestamps.
    """
    swap_start, swap_end = _local_day_range_to_utc_z_strings(
        date_yyyy_mm_dd=date_yyyy_mm_dd,
        timezone_name=timezone_name,
    )

    return await create_shift_swap_request(
        schedule_id=schedule_id,
        beneficiary_user_id=beneficiary_user_id,
        swap_start=swap_start,
        swap_end=swap_end,
        description=description
        or f"Shift swap request for {date_yyyy_mm_dd} ({timezone_name})",
        dry_run=dry_run,
    )


@mcp.tool()
async def create_shift_swap_request_for_time_range(
    schedule_id: str,
    beneficiary_user_id: str,
    start_local: str,
    end_local: str,
    timezone_name: str = "Europe/Warsaw",
    description: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Create a shift swap request for a custom local time range.

    Args:
        schedule_id: Schedule ID.
        beneficiary_user_id: User requesting coverage.
        start_local: Local start datetime, e.g. 2026-05-23T09:00:00.
        end_local: Local end datetime, e.g. 2026-05-23T17:00:00.
        timezone_name: Local timezone.
        description: Optional message.
        dry_run: If true, only reports payload.
    """
    swap_start, swap_end = _local_range_to_utc_z_strings(
        start_local=start_local,
        end_local=end_local,
        timezone_name=timezone_name,
    )

    return await create_shift_swap_request(
        schedule_id=schedule_id,
        beneficiary_user_id=beneficiary_user_id,
        swap_start=swap_start,
        swap_end=swap_end,
        description=description
        or f"Shift swap request for {start_local} - {end_local} ({timezone_name})",
        dry_run=dry_run,
    )


@mcp.tool()
async def update_shift_swap_request(
    shift_swap_id: str,
    schedule_id: Optional[str] = None,
    beneficiary_user_id: Optional[str] = None,
    swap_start: Optional[str] = None,
    swap_end: Optional[str] = None,
    description: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Update a shift swap request.

    Only provided fields are changed. Existing fields are preserved where possible.
    """
    existing = await get_shift_swap_request(shift_swap_id)

    payload: Dict[str, Any] = {
        "schedule": schedule_id or existing.get("schedule"),
        "swap_start": swap_start or existing.get("swap_start"),
        "swap_end": swap_end or existing.get("swap_end"),
        "beneficiary": beneficiary_user_id or existing.get("beneficiary"),
    }

    if description is not None:
        payload["description"] = description
    elif existing.get("description") is not None:
        payload["description"] = existing.get("description")

    if dry_run:
        return {
            "dry_run": True,
            "shift_swap_id": shift_swap_id,
            "previous": existing,
            "payload": payload,
        }

    updated = await _request(
        "PUT",
        f"/api/v1/shift_swaps/{shift_swap_id}/",
        json=payload,
    )

    verify = await get_shift_swap_request(shift_swap_id)

    return {
        "dry_run": False,
        "shift_swap_id": shift_swap_id,
        "updated_shift_swap": updated,
        "verified_shift_swap": verify,
    }


@mcp.tool()
async def delete_shift_swap_request(
    shift_swap_id: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Delete a shift swap request.
    """
    existing = await get_shift_swap_request(shift_swap_id)

    if dry_run:
        return {
            "dry_run": True,
            "would_delete": True,
            "shift_swap_id": shift_swap_id,
            "current_shift_swap": existing,
        }

    await _request("DELETE", f"/api/v1/shift_swaps/{shift_swap_id}/")

    return {
        "dry_run": False,
        "deleted": True,
        "shift_swap_id": shift_swap_id,
        "deleted_shift_swap": existing,
    }


if __name__ == "__main__":
    mcp.run()