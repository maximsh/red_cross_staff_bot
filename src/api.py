import os
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, Response, RedirectResponse
import urllib.request
import hashlib
import json

from src.auth import get_auth_dependency
from src.database import (
    upsert_employee,
    record_event,
    get_current_status,
    get_all_statuses,
    get_today_events,
    get_valid_actions,
    set_employee_aliases,
)

# Load configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
auth = get_auth_dependency(BOT_TOKEN)

router = APIRouter()

# Schema for incoming request body
class EventRequest(BaseModel):
    note: Optional[str] = ""

def download_avatar_sync(user_id: int, photo_url: str):
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "avatars", f"{user_id}.jpg")
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    try:
        req = urllib.request.Request(photo_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = response.read()
        with open(local_path, "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"Failed to download avatar for {user_id}:", e)

def transform_photo_url(employee: dict):
    if employee and employee.get("photo_url"):
        url_hash = hashlib.md5(employee["photo_url"].encode()).hexdigest()[:8]
        employee["photo_url"] = f"/api/avatar/{employee['telegram_id']}?v={url_hash}"
    return employee

@router.get("/api/avatar/{telegram_id}")
def get_avatar(telegram_id: int):
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "avatars", f"{telegram_id}.jpg")
    
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return FileResponse(local_path)
        
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUserProfilePhotos?user_id={telegram_id}&limit=1"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
        
        if data.get("ok") and data["result"]["total_count"] > 0:
            photos = data["result"]["photos"][0]
            file_id = photos[-1]["file_id"]
            
            file_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
            req2 = urllib.request.Request(file_url)
            with urllib.request.urlopen(req2) as response2:
                data2 = json.loads(response2.read())
                
            if data2.get("ok"):
                file_path = data2["result"]["file_path"]
                download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
                
                req3 = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req3) as response3:
                    img_data = response3.read()
                
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(img_data)
                
                return FileResponse(local_path)
    except Exception as e:
        print(f"Failed to fetch avatar via bot API for {telegram_id}:", e)

    status = get_current_status(telegram_id)
    if status and status.get("photo_url"):
        return RedirectResponse(status["photo_url"])

    return Response(status_code=404)

@router.post("/api/checkin")
def checkin(background_tasks: BackgroundTasks, payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
    try:
        user_id = user["id"]
        first_name = user["first_name"]
        last_name = user.get("last_name") or ""
        username = user.get("username") or ""
        photo_url = user.get("photo_url") or ""

        status_data = get_current_status(user_id)
        
        if photo_url and photo_url.startswith("http"):
            local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "avatars", f"{user_id}.jpg")
            if not status_data or status_data.get("photo_url") != photo_url or not os.path.exists(local_path):
                background_tasks.add_task(download_avatar_sync, user_id, photo_url)

        upsert_employee(user_id, first_name, last_name, username, photo_url)

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
def checkout(payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
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
def field_start(payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
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
def field_end(payload: Optional[EventRequest] = None, user: dict = Depends(auth)):
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
def get_status_by_id(telegramId: int, user: dict = Depends(auth)):
    try:
        status_data = get_current_status(telegramId)
        if not status_data:
            return JSONResponse(status_code=404, content={"error": "Працівника не знайдено"})

        valid_actions = get_valid_actions(status_data["status"])
        transform_photo_url(status_data)
        return {**status_data, "validActions": valid_actions}
    except Exception as e:
        print("Status error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.get("/api/my-status")
def get_my_status(background_tasks: BackgroundTasks, user: dict = Depends(auth)):
    try:
        user_id = user["id"]
        first_name = user["first_name"]
        last_name = user.get("last_name") or ""
        username = user.get("username") or ""
        photo_url = user.get("photo_url") or ""

        status_data = get_current_status(user_id)
        
        if photo_url and photo_url.startswith("http"):
            local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "avatars", f"{user_id}.jpg")
            if not status_data or status_data.get("photo_url") != photo_url or not os.path.exists(local_path):
                background_tasks.add_task(download_avatar_sync, user_id, photo_url)

        upsert_employee(user_id, first_name, last_name, username, photo_url)

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

        transform_photo_url(res_data)
        return {**res_data, "validActions": valid_actions, "todayEvents": today_events, "isAdmin": is_admin}
    except Exception as e:
        print("My status error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

@router.get("/api/statuses")
def get_statuses(user: dict = Depends(auth)):
    try:
        statuses = get_all_statuses()
        for s in statuses:
            transform_photo_url(s)

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
def get_today_events_by_id(telegramId: int, user: dict = Depends(auth)):
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
def admin_set_status(payload: AdminSetStatusRequest, user: dict = Depends(auth)):
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

class AdminSetAliasesRequest(BaseModel):
    telegram_id: int
    aliases: str

@router.post("/api/admin/set-aliases")
def admin_set_aliases(payload: AdminSetAliasesRequest, user: dict = Depends(auth)):
    try:
        if user["id"] not in ADMIN_IDS:
            return JSONResponse(status_code=403, content={"error": "У вас немає прав адміністратора"})
            
        target_id = payload.telegram_id
        aliases_str = payload.aliases
        
        current_status = get_current_status(target_id)
        if not current_status:
            return JSONResponse(status_code=404, content={"error": "Працівника не знайдено"})
            
        set_employee_aliases(target_id, aliases_str)
        return {"success": True, "aliases": aliases_str}
    except Exception as e:
        print("Admin set aliases error:", e)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
