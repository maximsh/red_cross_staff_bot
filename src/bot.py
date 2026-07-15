import os
import html
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import (
    Message,
    TelegramObject,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from aiogram.filters import Command, CommandStart

# Load config from env
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "staff")

# Shared holder for bot username
bot_username_holder = {"username": ""}

# Initialize Bot and Dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AutoRegisterMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        # Capture bot username if not set yet
        current_bot = data.get("bot")
        if current_bot and not bot_username_holder["username"]:
            try:
                bot_info = await current_bot.get_me()
                bot_username_holder["username"] = bot_info.username
            except Exception as e:
                print("Error fetching bot info:", e)

        # Auto-register user on any interaction
        user = data.get("event_from_user")
        if user:
            from src.database import upsert_employee
            try:
                upsert_employee(
                    telegram_id=user.id,
                    first_name=user.first_name,
                    last_name=user.last_name or "",
                    username=user.username or "",
                )
            except Exception as e:
                print("Error in auto-registration middleware:", e)

        return await handler(event, data)

# Register the middleware
dp.update.outer_middleware(AutoRegisterMiddleware())

def escape_html(text: str) -> str:
    return html.escape(text, quote=True)

def build_private_keyboard(web_app_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Відмітитися 🏢", web_app=WebAppInfo(url=f"{web_app_url}/"))],
            [
                KeyboardButton(
                    text="📊 Панель контролю 👥",
                    web_app=WebAppInfo(url=f"{web_app_url}/?tgWebAppStartParam=dashboard"),
                )
            ],
        ],
        resize_keyboard=True,
    )

async def handle_quick_action(message: Message, event_type: str, success_msg: str, action_name: str):
    user = message.from_user
    if not user:
        return

    from src.database import upsert_employee, get_current_status, get_valid_actions, record_event

    # Ensure user is registered
    upsert_employee(user.id, user.first_name, user.last_name or "", user.username or "")

    current_status = get_current_status(user.id)
    status = current_status.get("status") if current_status else "offline"
    valid_actions = get_valid_actions(status)

    if event_type not in valid_actions:
        status_map = {
            "offline": "відсутній",
            "in_office": "на роботі",
            "field_trip": "на виїзді",
        }
        await message.reply(
            f"❌ <b>{escape_html(user.first_name)}</b>, не можна зробити \"{action_name}\", оскільки ваш статус: <b>{status_map.get(status, status)}</b>.",
            parse_mode="HTML",
        )
        return

    # Record the event
    record_event(user.id, event_type)

    # Format local time (Europe/Kyiv, UTC+3)
    kyiv_time = datetime.now(timezone.utc) + timedelta(hours=3)
    time_str = kyiv_time.strftime("%H:%M")

    display_name = f"{user.first_name} {user.last_name or ''}".strip()
    await message.reply(
        f"{success_msg} <b>{escape_html(display_name)}</b> о <b>{time_str}</b>",
        parse_mode="HTML",
    )

def build_active_status_report() -> str:
    from src.database import get_all_statuses

    statuses = get_all_statuses()
    active_employees = [emp for emp in statuses if emp.get("status") in ("in_office", "field_trip")]

    if not active_employees:
        return "👥 Зараз нікого немає на роботі."

    def format_time(iso_string):
        if not iso_string:
            return ""
        try:
            # Parse ISO string
            clean_str = iso_string.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            # Convert to Kyiv timezone (UTC+3)
            kyiv_dt = dt.astimezone(timezone(timedelta(hours=3)))
            return kyiv_dt.strftime("%H:%M")
        except Exception as e:
            print("format_time error:", e)
            return ""

    # Grouping
    groups = {
        "Офіс": [],
        "Доміще": [],
        "Амосова": [],
        "Склад": [],
        "На виїзді": []
    }

    for emp in active_employees:
        status = emp.get("status")
        note = emp.get("note") or ""
        note_lower = note.lower()

        if status == "field_trip":
            groups["На виїзді"].append(emp)
        else:
            if "склад" in note_lower:
                groups["Склад"].append(emp)
            elif "амосова" in note_lower:
                groups["Амосова"].append(emp)
            elif "доміще" in note_lower:
                groups["Доміще"].append(emp)
            else:
                groups["Офіс"].append(emp)

    text = "<b>📋 Зараз на роботі:</b>\n\n"

    for group_name in ["Офіс", "Доміще", "Амосова", "Склад", "На виїзді"]:
        group_emps = groups[group_name]
        if not group_emps:
            continue

        if group_name == "На виїзді":
            text += f"🚗 <b>{group_name}:</b>\n"
        else:
            text += f"🏢 <b>{group_name}:</b>\n"

        for emp in group_emps:
            name = f"{emp.get('first_name')} {emp.get('last_name') or ''}".strip()
            time_str = format_time(emp.get("last_event_at"))
            note = emp.get("note")

            if group_name == "На виїзді":
                line = f"  🟡 <b>{escape_html(name)}</b> (з {time_str})"
            else:
                line = f"  🟢 <b>{escape_html(name)}</b> (з {time_str})"

            if note:
                line += f" <i>[{escape_html(note)}]</i>"

            text += line + "\n"
        text += "\n"

    return text.strip()

# Command Handlers

@dp.message(Command("in", "checkin", "office"))
async def cmd_checkin(message: Message):
    await handle_quick_action(message, "checkin", "🟢 На місці:", "прихід")

@dp.message(Command("away", "trip"))
async def cmd_away(message: Message):
    await handle_quick_action(message, "field_start", "🚗 Виїхав:", "виїзд")

@dp.message(Command("back", "return"))
async def cmd_back(message: Message):
    await handle_quick_action(message, "field_end", "↩️ Повернувся в офіс:", "повернення")

@dp.message(Command("out", "checkout", "home"))
async def cmd_checkout(message: Message):
    await handle_quick_action(message, "checkout", "🏠 Пішов додому:", "вихід")

@dp.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    chat_private = message.chat.type == "private"
    bot_username = bot_username_holder["username"] or (await bot.get_me()).username

    if not chat_private:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📋 Відкрити систему",
                        url=f"https://t.me/{bot_username}/{APP_SHORT_NAME}",
                    )
                ]
            ]
        )
        await message.reply(
            "👋 Робота з системою контролю присутності відбувається через особистий діалог з ботом.",
            reply_markup=keyboard,
        )
        return

    keyboard = build_private_keyboard(WEBAPP_URL)
    await message.reply(
        "👋 *Вітаю\\!*\n\n"
        "Кнопки для управління системою тепер знаходяться *внизу екрана* (замість звичайної клавіатури)\\.\n\n"
        "Оберіть потрібну дію:",
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: Message, bot: Bot):
    chat_private = message.chat.type == "private"
    bot_username = bot_username_holder["username"] or (await bot.get_me()).username

    if not chat_private:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Панель контролю",
                        url=f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp=dashboard",
                    )
                ]
            ]
        )
        await message.reply(
            "📊 Панель контролю відкривається в особистому чаті з ботом:", reply_markup=keyboard
        )
        return

    keyboard = build_private_keyboard(WEBAPP_URL)
    await message.reply("📊 Панель контролю доступна на клавіатурі знизу:", reply_markup=keyboard)

@dp.message(Command("status"))
async def cmd_status(message: Message, bot: Bot):
    report_text = build_active_status_report()
    chat_private = message.chat.type == "private"
    bot_username = bot_username_holder["username"] or (await bot.get_me()).username

    if chat_private:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Панель контролю",
                        web_app=WebAppInfo(url=f"{WEBAPP_URL}/?tgWebAppStartParam=dashboard"),
                    )
                ]
            ]
        )
    else:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Панель контролю",
                        url=f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp=dashboard",
                    )
                ]
            ]
        )

    await message.reply(report_text, parse_mode="HTML", reply_markup=keyboard)

# Handle channel posts

@dp.channel_post(F.text)
async def handle_channel_post(channel_post: Message, bot: Bot):
    text = channel_post.text or ""
    bot_username = bot_username_holder["username"] or (await bot.get_me()).username

    if text.startswith("/start"):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📋 Відкрити систему",
                        url=f"https://t.me/{bot_username}/{APP_SHORT_NAME}",
                    )
                ]
            ]
        )
        await channel_post.reply(
            "👋 Робота з системою відбувається через особистий діалог з ботом:",
            reply_markup=keyboard,
        )
    elif text.startswith("/status"):
        report_text = build_active_status_report()
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Панель контролю",
                        url=f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp=dashboard",
                    )
                ]
            ]
        )
        await channel_post.reply(report_text, parse_mode="HTML", reply_markup=keyboard)
    elif text.startswith("/dashboard"):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📊 Панель контролю",
                        url=f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp=dashboard",
                    )
                ]
            ]
        )
        await channel_post.reply("📊 Панель контролю команди:", reply_markup=keyboard)

# AI-powered group chat message handler

@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, ~F.text.startswith("/"))
async def handle_group_text(message: Message):
    """
    Analyze free-text messages in group chats using AI (Google Gemini)
    to detect status change intents and automatically update employee status.
    """
    user = message.from_user
    if not user or not message.text:
        return

    from src.nlp import analyze_message, format_note, GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return  # AI analysis disabled — no API key configured

    from src.database import get_current_status, get_valid_actions, record_event

    # Get current status
    current_status = get_current_status(user.id)
    status = current_status.get("status") if current_status else "offline"

    # Send message to AI for analysis
    result = await analyze_message(message.text, status)
    if not result:
        return  # Not a status-related message — ignore silently

    action = result["action"]
    includes_sender = result.get("includes_sender", True)
    mentioned_users = result.get("mentioned_users", [])
    is_plural = result.get("is_plural", False)

    from src.database import get_all_statuses, upsert_employee
    all_employees = get_all_statuses()

    target_users = []

    if includes_sender:
        target_users.append({
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name or "",
            "status": status,
        })

    if mentioned_users:
        for emp in all_employees:
            emp_first = emp.get("first_name", "").lower()
            emp_last = (emp.get("last_name") or "").lower()
            emp_username = (emp.get("username") or "").lower()

            emp_aliases = [a.strip().lower() for a in (emp.get("aliases") or "").split(",") if a.strip()]

            for mention in mentioned_users:
                m_lower = mention.lower()
                # Use length > 2 to avoid matching very short fragments if Gemini returned something weird
                if len(m_lower) > 2:
                    match = (m_lower in emp_first or m_lower in emp_last or m_lower in emp_username)
                    if not match:
                        for alias in emp_aliases:
                            if m_lower in alias or alias in m_lower:
                                match = True
                                break
                    if match:
                        if emp["telegram_id"] not in [u["id"] for u in target_users]:
                            target_users.append({
                                "id": emp["telegram_id"],
                                "first_name": emp["first_name"],
                                "last_name": emp["last_name"] or "",
                                "status": emp["status"],
                            })
                        break

    if is_plural and not mentioned_users:
        sender_note = current_status.get("note") if current_status else ""
        sender_time_str = current_status.get("last_event_at") if current_status else None

        if sender_time_str:
            try:
                sender_time = datetime.fromisoformat(sender_time_str.replace("Z", "+00:00"))
                for emp in all_employees:
                    if emp["telegram_id"] == user.id:
                        continue
                    if emp["status"] != status:
                        continue
                    if sender_note and emp["note"] != sender_note:
                        continue

                    emp_time_str = emp.get("last_event_at")
                    if emp_time_str:
                        emp_time = datetime.fromisoformat(emp_time_str.replace("Z", "+00:00"))
                        diff = abs((sender_time - emp_time).total_seconds())
                        if diff < 120:  # 2 minutes window
                            if emp["telegram_id"] not in [u["id"] for u in target_users]:
                                target_users.append({
                                    "id": emp["telegram_id"],
                                    "first_name": emp["first_name"],
                                    "last_name": emp["last_name"] or "",
                                    "status": emp["status"],
                                })
            except Exception as e:
                print("Error grouping users:", e)

    if not target_users:
        return

    # Build note from extracted destination, duration, and car info
    note = format_note(result.get("destination"), result.get("duration"), result.get("car_info"))

    updates = []

    for t_user in target_users:
        event_type = action
        if action == "update":
            if t_user["status"] == "offline":
                event_type = "checkout"
            elif t_user["status"] == "in_office":
                event_type = "checkin"
            elif t_user["status"] == "field_trip":
                event_type = "field_start"
            else:
                event_type = "checkin"

        # Record the event for each user
        try:
            record_event(t_user["id"], event_type, note)
            display_name = f"{t_user['first_name']} {t_user['last_name']}".strip()
            updates.append(escape_html(display_name))
        except Exception as e:
            print(f"Failed to record event for {t_user['id']}: {e}")

    if not updates:
        return

    # Format confirmation
    kyiv_time = datetime.now(timezone.utc) + timedelta(hours=3)
    time_str = kyiv_time.strftime("%H:%M")

    action_messages = {
        "checkin": "🟢 На місці:",
        "checkout": "🏠 Пішов додому:",
        "field_start": "🚗 Виїхав:",
        "field_end": "↩️ Повернувся в офіс:",
        "update": "ℹ️ Оновлено статус:",
    }

    msg = f"{action_messages.get(action, '📌')} <b>{', '.join(updates)}</b> о <b>{time_str}</b>"
    if note:
        msg += f"\n{note}"

    await message.reply(msg, parse_mode="HTML")

# Fallback handler for private text messages

@dp.message(F.chat.type == "private", F.text)
async def fallback_private(message: Message):
    keyboard = build_private_keyboard(WEBAPP_URL)
    await message.reply(
        "Використовуйте кнопки на клавіатурі внизу екрана для взаємодії з системою.",
        reply_markup=keyboard,
    )
