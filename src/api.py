import os
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.auth import get_auth_dependency
from src.database import (
    upsert_employee,
    record_event,
    get_current_status,
    get_all_statuses,
    get_today_events,
    get_valid_actions,
)

# Load configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
auth = get_auth_dependency(BOT_TOKEN)

router = APIRouter()

# Schema for incoming request body
class EventRequest(BaseModel):
    note: Optional[str] = ""

@router.post("/api/checkin")
async def checkin(payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
    try:
        user_id = user["id"]
        first_name = user["first_name"]
        last_name = user.get("last_name") or ""
        username = user.get("username") or ""

        upsert_employee(user_id, first_name, last_name, username)

        current_status = get_current_status(user_id)
        status_name = current_status["status"] if current_status else "offline"
        valid_actions = get_valid_actions(status_name)

        if "checkin" not in valid_actions:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Не можна зареєструвати прихід у поточному стані",
                    "currentStatus": status_name,
                },
            )

        note = payload.note if payload and payload.note else ""
        result = record_event(user_id, "checkin", note)
        return {"success": True, **result}
    except Exception as e:
        print("Checkin error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.post("/api/checkout")
async def checkout(payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
    try:
        user_id = user["id"]
        current_status = get_current_status(user_id)
        status_name = current_status["status"] if current_status else "offline"
        valid_actions = get_valid_actions(status_name)

        if "checkout" not in valid_actions:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Не можна зареєструвати вихід у поточному стані",
                    "currentStatus": status_name,
                },
            )

        note = payload.note if payload and payload.note else ""
        result = record_event(user_id, "checkout", note)
        return {"success": True, **result}
    except Exception as e:
        print("Checkout error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.post("/api/field-start")
async def field_start(payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
    try:
        user_id = user["id"]
        current_status = get_current_status(user_id)
        status_name = current_status["status"] if current_status else "offline"
        valid_actions = get_valid_actions(status_name)

        if "field_start" not in valid_actions:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Не можна почати виїзд у поточному стані",
                    "currentStatus": status_name,
                },
            )

        note = payload.note if payload and payload.note else ""
        result = record_event(user_id, "field_start", note)
        return {"success": True, **result}
    except Exception as e:
        print("Field start error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.post("/api/field-end")
async def field_end(payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
    try:
        user_id = user["id"]
        current_status = get_current_status(user_id)
        status_name = current_status["status"] if current_status else "offline"
        valid_actions = get_valid_actions(status_name)

        if "field_end" not in valid_actions:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Не можна завершити виїзд у поточному стані",
                    "currentStatus": status_name,
                },
            )

        note = payload.note if payload and payload.note else ""
        result = record_event(user_id, "field_end", note)
        return {"success": True, **result}
    except Exception as e:
        print("Field end error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.get("/api/status/{telegramId}")
async def get_status_by_id(telegramId: int, user: dict = Depends(auth)):
    try:
        status_data = get_current_status(telegramId)
        if not status_data:
            return JSONResponse(status_code=404, content={"error": "Працівника не знайдено"})

        valid_actions = get_valid_actions(status_data["status"])
        return {**status_data, "validActions": valid_actions}
    except Exception as e:
        print("Status error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.get("/api/my-status")
async def get_my_status(user: dict = Depends(auth)):
    try:
        user_id = user["id"]
        first_name = user["first_name"]
        last_name = user.get("last_name") or ""
        username = user.get("username") or ""

        upsert_employee(user_id, first_name, last_name, username)

        status_data = get_current_status(user_id)
        status_name = status_data["status"] if status_data else "offline"
        valid_actions = get_valid_actions(status_name)
        today_events = get_today_events(user_id)

        res_data = status_data or {
            "telegram_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "status": "offline",
            "last_event_at": None,
        }

        is_admin = user_id in ADMIN_IDS

        return {**res_data, "validActions": valid_actions, "todayEvents": today_events, "isAdmin": is_admin}
    except Exception as e:
        print("My status error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.get("/api/statuses")
async def get_statuses(user: dict = Depends(auth)):
    try:
        statuses = get_all_statuses()

        in_office_count = len([s for s in statuses if s["status"] == "in_office"])
        field_trip_count = len([s for s in statuses if s["status"] == "field_trip"])
        offline_count = len([s for s in statuses if s["status"] == "offline"])

        summary = {
            "in_office": in_office_count,
            "field_trip": field_trip_count,
            "offline": offline_count,
            "total": len(statuses),
            "isAdmin": user["id"] in ADMIN_IDS
        }

        return {"employees": statuses, "summary": summary}
    except Exception as e:
        print("Statuses error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.get("/api/today/{telegramId}")
async def get_today_events_by_id(telegramId: int, user: dict = Depends(auth)):
    try:
        events = get_today_events(telegramId)
        return {"events": events}
    except Exception as e:
        print("Today events error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

class AdminSetStatusRequest(BaseModel):
    telegram_id: int
    action: str
    note: Optional[str] = "Змінено адміністратором"

@router.post("/api/admin/set-status")
async def admin_set_status(payload: AdminSetStatusRequest, user: dict = Depends(auth)):
    try:
        if user["id"] not in ADMIN_IDS:
            return JSONResponse(status_code=403, content={"error": "У вас немає прав адміністратора"})

        target_id = payload.telegram_id
        action = payload.action

        current_status = get_current_status(target_id)
        if not current_status:
            return JSONResponse(status_code=404, content={"error": "Працівника не знайдено"})

        status_name = current_status["status"]
        valid_actions = get_valid_actions(status_name)

        if action not in valid_actions:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"Не можна виконати дію '{action}' у поточному стані",
                    "currentStatus": status_name,
                },
            )

        result = record_event(target_id, action, payload.note)
        return {"success": True, **result}
    except Exception as e:
        print("Admin set status error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
