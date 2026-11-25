import os
import html
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

KYIV_TZ = ZoneInfo("Europe/Kyiv")
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import (
    Message,
    TelegramObject,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllGroupChats,
)
from aiogram.filters import Command, CommandStart

# Load config from env
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "staff")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

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

        # Auto-register user ONLY on private interaction with the bot
        # (prevents auto-registering untracked chat members or guests in groups)
        is_private = False
        if hasattr(event, "message") and event.message and event.message.chat:
            is_private = (event.message.chat.type == "private")
        elif hasattr(event, "callback_query") and event.callback_query and event.callback_query.message:
            is_private = (event.callback_query.message.chat.type == "private")

        user = data.get("event_from_user")
        if user and is_private:
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
    if not current_status:
        await message.reply(
            f"❌ <b>{escape_html(user.first_name)}</b>, ви не є зареєстрованим співробітником або були видалені з системи.",
            parse_mode="HTML",
        )
        return

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

    # Format local time (Europe/Kyiv)
    kyiv_time = datetime.now(KYIV_TZ)
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
            # Convert to Kyiv timezone
            kyiv_dt = dt.astimezone(KYIV_TZ)
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

@dp.message(Command("add_employee", "add_user", "add"))
async def cmd_add_employee(message: Message):
    if not await is_admin(message):
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    target_user = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user

    if not target_user:
        await message.reply(
            "ℹ️ <b>Додавання співробітника або волонтера до системи:</b>\n\n"
            "Щоб зареєструвати людину, надішліть команду <code>/add</code> <b>у відповідь</b> на її повідомлення в чаті.",
            parse_mode="HTML"
        )
        return

    from src.database import upsert_employee, restore_employee
    restore_employee(target_user.id)
    upsert_employee(
        telegram_id=target_user.id,
        first_name=target_user.first_name,
        last_name=target_user.last_name or "",
        username=target_user.username or "",
    )
    name = f"{target_user.first_name} {target_user.last_name or ''}".strip()
    await message.reply(
        f"✅ Співробітника/волонтера <b>{escape_html(name)}</b> (ID: <code>{target_user.id}</code>) успішно додано до системи!",
        parse_mode="HTML"
    )

@dp.message(Command("delete_employee", "delete_user", "remove_employee", "delete"))
async def cmd_delete_employee(message: Message):
    user = message.from_user
    if not user:
        return

    if user.id not in ADMIN_IDS:
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    from src.database import delete_employee, get_employee, get_employee_by_username

    target_id = None
    target_emp = None

    # Check 1: replied message
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
        target_emp = get_employee(target_id)
    else:
        # Check 2: command arguments
        text = message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            arg = parts[1].strip()
            if arg.isdigit():
                target_id = int(arg)
                target_emp = get_employee(target_id)
            else:
                target_emp = get_employee_by_username(arg)
                if target_emp:
                    target_id = target_emp["telegram_id"]

    if not target_id:
        await message.reply(
            "ℹ️ <b>Видалення співробітника</b>\n\n"
            "Способи використання:\n"
            "• Відповісти на повідомлення користувача: <code>/delete</code>\n"
            "• Вказати username: <code>/delete @username</code>\n"
            "• Вказати ID: <code>/delete 123456789</code>",
            parse_mode="HTML",
        )
        return

    if target_id == user.id:
        await message.reply("❌ Не можна видалити власного користувача.")
        return

    if not target_emp:
        target_emp = get_employee(target_id)

    name_str = f"{target_emp['first_name']} {target_emp.get('last_name', '')}".strip() if target_emp else f"ID: {target_id}"

    delete_employee(target_id, deleted_by=user.id)
    await message.reply(
        f"✅ Співробітника <b>{escape_html(name_str)}</b> успішно видалено з системи.",
        parse_mode="HTML",
    )

@dp.message(Command("restore_employee", "restore_user", "restore"))
async def cmd_restore_employee(message: Message):
    user = message.from_user
    if not user:
        return

    if user.id not in ADMIN_IDS:
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    from src.database import restore_employee, get_employee_by_username

    target_id = None
    text = message.text or ""
    parts = text.split(maxsplit=1)

    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) > 1:
        arg = parts[1].strip()
        if arg.isdigit():
            target_id = int(arg)
        else:
            emp = get_employee_by_username(arg)
            if emp:
                target_id = emp["telegram_id"]

    if not target_id:
        await message.reply(
            "ℹ️ <b>Відновлення співробітника</b> (зняття блокування на реєстрацію)\n\n"
            "Використання:\n"
            "• <code>/restore @username</code>\n"
            "• <code>/restore &lt;telegram_id&gt;</code>\n"
            "• Або відповіддю на повідомлення: <code>/restore</code>",
            parse_mode="HTML",
        )
        return

    restore_employee(target_id)
    await message.reply(
        f"✅ Співробітника (ID: <code>{target_id}</code>) відновлено. Тепер він знову може бути доданий до системи.",
        parse_mode="HTML",
    )

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


# Helpers

import re

def normalize_name(text: str) -> str:
    if not text:
        return ""
    t = text.lower().strip().lstrip("@")
    t = re.sub(r'^(?:волонтер(?:ка)?|водій|пан|пані|координатор)\s+', '', t)
    return t.strip()

async def is_admin(message: Message) -> bool:
    user = message.from_user
    if not user:
        return False
    if user.id in ADMIN_IDS:
        return True
    if message.chat and message.chat.type in ("group", "supergroup"):
        try:
            member = await message.chat.get_member(user.id)
            if member.status in ("creator", "administrator"):
                return True
        except Exception:
            pass
    return False


# Topic and Alias Management Commands

def get_effective_thread_id(message: Message):
    """Return message_thread_id, mapping the General forum topic (None) to 1."""
    thread_id = message.message_thread_id
    # Telegram often omits is_forum in message.chat, so treat any supergroup
    # message without a thread as coming from the General topic (ID 1).
    if thread_id is None and (
        getattr(message.chat, "is_forum", False) or message.chat.type == "supergroup"
    ):
        return 1
    return thread_id

async def register_bot_commands(target_bot: Bot):
    """Register bot commands for private and group/forum chats."""
    commands = [
        BotCommand(command="status", description="Показати хто зараз на роботі"),
        BotCommand(command="in", description="На місці (початок роботи)"),
        BotCommand(command="away", description="Виїзд у справах"),
        BotCommand(command="back", description="Повернення в офіс"),
        BotCommand(command="out", description="Пішов додому (кінець зміни)"),
        BotCommand(command="dashboard", description="Відкрити панель контролю"),
        BotCommand(command="topic_id", description="Показати ID гілки та чату"),
        BotCommand(command="set_main_topic", description="Прив'язати головну гілку"),
        BotCommand(command="set_trips_topic", description="Прив'язати гілку 'Виїзди'"),
        BotCommand(command="monitored_topics", description="Список підключених гілок"),
        BotCommand(command="add", description="Додати співробітника (відповіддю)"),
        BotCommand(command="alias", description="Встановити псевдоніми"),
    ]
    await target_bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    await target_bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())

@dp.message(Command("topic_id", "thread_id"))
async def cmd_topic_id(message: Message):
    chat = message.chat
    raw_thread_id = message.message_thread_id
    is_forum = getattr(chat, 'is_forum', False) or (raw_thread_id is not None)
    thread_id = get_effective_thread_id(message)

    from src.database import is_topic_monitored
    is_trips = is_topic_monitored(chat.id, thread_id, "trips")
    is_main = is_topic_monitored(chat.id, thread_id, "main")

    if is_trips and is_main:
        status_str = "🟢 Моніториться як головна гілка та 'Виїзди'"
    elif is_main:
        status_str = "🟢 Моніториться як головна гілка"
    elif is_trips:
        status_str = "🟢 Моніториться як 'Виїзди'"
    else:
        status_str = "⚪ Не моніториться"

    if thread_id is not None:
        thread_label = f"<code>{thread_id}</code>" + (" (Загальна гілка)" if is_forum and raw_thread_id is None else "")
    else:
        thread_label = "<code>Загальний чат (без гілки)</code>"

    await message.reply(
        f"ℹ️ <b>Інформація про гілку/чат:</b>\n\n"
        f"💬 Чат: <b>{escape_html(chat.title or '')}</b>\n"
        f"🆔 Chat ID: <code>{chat.id}</code>\n"
        f"🧵 Thread ID: {thread_label}\n"
        f"📂 Режим форуму: <b>{'Так' if is_forum else 'Ні'}</b>\n"
        f"📊 Статус теми: {status_str}",
        parse_mode="HTML"
    )

def _extract_topic_params(message: Message, default_name: str):
    """Extract (thread_id, topic_name) from a topic command message."""
    thread_id = get_effective_thread_id(message)
    parts = (message.text or "").strip().split()
    topic_name = default_name

    if thread_id is None:
        if len(parts) > 1 and parts[1].isdigit():
            thread_id = int(parts[1])
            if len(parts) > 2:
                topic_name = " ".join(parts[2:])
    elif len(parts) > 1:
        topic_name = " ".join(parts[1:])

    return thread_id, topic_name

@dp.message(Command("set_main_topic", "bind_main", "track_main"))
async def cmd_set_main_topic(message: Message):
    if not await is_admin(message):
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    thread_id, topic_name = _extract_topic_params(message, "Головна гілка")
    if thread_id is None:
        await message.reply(
            "⚠️ <b>Цю команду потрібно викликати всередині потрібної гілки головного чату.</b>\n\n"
            "Перейдіть у потрібну гілку та напишіть <code>/set_main_topic</code>, "
            "або вкажіть Thread ID вручну: <code>/set_main_topic &lt;thread_id&gt;</code>.",
            parse_mode="HTML"
        )
        return

    from src.database import set_main_topic
    set_main_topic(message.chat.id, thread_id, topic_name)

    await message.reply(
        f"✅ <b>Гілку підключено як єдину активну гілку головного чату!</b>\n\n"
        f"📌 Назва: <b>{escape_html(topic_name)}</b>\n"
        f"🆔 Chat ID: <code>{message.chat.id}</code>\n"
        f"🧵 Thread ID: <code>{thread_id}</code>\n\n"
        f"Тепер у цьому чаті система опрацьовуватиме текстові повідомлення лише з цієї гілки.",
        parse_mode="HTML"
    )

@dp.message(Command("unset_main_topic", "unbind_main"))
async def cmd_unset_main_topic(message: Message):
    if not await is_admin(message):
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    thread_id, _ = _extract_topic_params(message, "")
    if thread_id is None:
        await message.reply(
            "⚠️ Викличте цю команду всередині гілки або вкажіть Thread ID: <code>/unset_main_topic &lt;thread_id&gt;</code>",
            parse_mode="HTML"
        )
        return

    from src.database import remove_monitored_topic
    remove_monitored_topic(message.chat.id, thread_id, "main")
    await message.reply(f"✅ Моніторинг головної гілки <code>{thread_id}</code> вимкнено.", parse_mode="HTML")

@dp.message(Command("set_trips_topic", "bind_trips", "track_trips"))
async def cmd_set_trips_topic(message: Message):
    if not await is_admin(message):
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    thread_id, topic_name = _extract_topic_params(message, "Виїзди")
    if thread_id is None:
        await message.reply(
            "⚠️ <b>Цю команду потрібно викликати всередині гілки (топіка) 'Виїзди'.</b>\n\n"
            "Перейдіть у потрібну гілку та напишіть <code>/set_trips_topic</code>, "
            "або вкажіть Thread ID вручну: <code>/set_trips_topic &lt;thread_id&gt;</code>.",
            parse_mode="HTML"
        )
        return

    from src.database import add_monitored_topic
    add_monitored_topic(message.chat.id, thread_id, "trips", topic_name)

    await message.reply(
        f"✅ <b>Гілку успішно підключено до моніторингу виїздів!</b>\n\n"
        f"📌 Назва: <b>{escape_html(topic_name)}</b>\n"
        f"🆔 Chat ID: <code>{message.chat.id}</code>\n"
        f"🧵 Thread ID: <code>{thread_id}</code>\n\n"
        f"Тепер текстові повідомлення співробітників та волонтерів у цій гілці будуть автоматично аналізуватися AI, "
        f"а статуси — оновлюватися в системі та відображатися на дашборді.",
        parse_mode="HTML"
    )

@dp.message(Command("unset_trips_topic", "unbind_trips"))
async def cmd_unset_trips_topic(message: Message):
    if not await is_admin(message):
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    thread_id, _ = _extract_topic_params(message, "")
    if thread_id is None:
        await message.reply(
            "⚠️ Викличте цю команду всередині гілки або вкажіть Thread ID: <code>/unset_trips_topic &lt;thread_id&gt;</code>",
            parse_mode="HTML"
        )
        return

    from src.database import remove_monitored_topic
    remove_monitored_topic(message.chat.id, thread_id, "trips")
    await message.reply(f"✅ Моніторинг виїздів для гілки <code>{thread_id}</code> вимкнено.", parse_mode="HTML")

@dp.message(Command("trips_topics", "main_topics", "monitored_topics"))
async def cmd_trips_topics(message: Message):
    from src.database import get_monitored_topics
    main_topics = get_monitored_topics("main")
    trips_topics = get_monitored_topics("trips")
    env_main_chat = os.getenv("MAIN_CHAT_ID")
    env_main_thread = os.getenv("MAIN_THREAD_ID")
    env_trips_chat = os.getenv("TRIPS_CHAT_ID")
    env_trips_thread = os.getenv("TRIPS_THREAD_ID")

    lines = []
    if main_topics or (env_main_chat and env_main_thread):
        lines.append("<b>Головні гілки:</b>")
        for t in main_topics:
            lines.append(f"• <b>{escape_html(t.get('topic_name') or 'Головна гілка')}</b> — Chat ID: <code>{t['chat_id']}</code>, Thread ID: <code>{t['thread_id']}</code>")
        if env_main_chat and env_main_thread:
            lines.append(f"• <b>З конфігурації .env</b> — Chat ID: <code>{env_main_chat}</code>, Thread ID: <code>{env_main_thread}</code>")

    if trips_topics or (env_trips_chat and env_trips_thread):
        if lines:
            lines.append("")
        lines.append("<b>Гілки виїздів:</b>")
        for t in trips_topics:
            lines.append(f"• <b>{escape_html(t.get('topic_name') or 'Виїзди')}</b> — Chat ID: <code>{t['chat_id']}</code>, Thread ID: <code>{t['thread_id']}</code>")
        if env_trips_chat and env_trips_thread:
            lines.append(f"• <b>З конфігурації .env</b> — Chat ID: <code>{env_trips_chat}</code>, Thread ID: <code>{env_trips_thread}</code>")

    if not lines:
        await message.reply(
            "ℹ️ Наразі немає налаштованих гілок.\n\n"
            "Щоб підключити гілку:\n"
            "• Для головного чату: зайдіть у потрібну гілку та напишіть <code>/set_main_topic</code>\n"
            "• Для виїздів: зайдіть у гілку 'Виїзди' та напишіть <code>/set_trips_topic</code>",
            parse_mode="HTML"
        )
    else:
        await message.reply(
            "📋 <b>Підключені гілки моніторингу:</b>\n\n" + "\n".join(lines),
            parse_mode="HTML"
        )

@dp.message(Command("alias", "aliases", "set_alias"))
async def cmd_alias(message: Message):
    if not await is_admin(message):
        await message.reply("❌ У вас немає прав адміністратора для цієї дії.")
        return

    from src.database import get_employee, get_employee_by_username, set_employee_aliases

    target_emp = None
    aliases_str = ""

    if message.reply_to_message and message.reply_to_message.from_user:
        target_emp = get_employee(message.reply_to_message.from_user.id)
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            aliases_str = parts[1].strip()
    else:
        text = (message.text or "").strip()
        parts = text.split(maxsplit=2)
        if len(parts) > 2:
            identifier = parts[1].strip()
            aliases_str = parts[2].strip()
            if identifier.isdigit():
                target_emp = get_employee(int(identifier))
            else:
                target_emp = get_employee_by_username(identifier)

    if not target_emp or not aliases_str:
        await message.reply(
            "ℹ️ <b>Встановлення псевдонімів (аліасів) для співробітника або волонтера</b>\n\n"
            "Дозволяє AI автоматично зіставляти згадки людей за скороченими іменами чи прізвиськами (наприклад, Сашко, Алекс).\n\n"
            "<b>Способи використання:</b>\n"
            "• Відповісти на повідомлення: <code>/alias Сашко, Саша</code>\n"
            "• За username: <code>/alias @username Сашко, Саша</code>\n"
            "• За Telegram ID: <code>/alias 123456789 Сашко, Саша</code>",
            parse_mode="HTML"
        )
        return

    set_employee_aliases(target_emp["telegram_id"], aliases_str)
    name = f"{target_emp['first_name']} {target_emp.get('last_name', '')}".strip()
    await message.reply(
        f"✅ Псевдоніми для <b>{escape_html(name)}</b> оновлено:\n<code>{escape_html(aliases_str)}</code>",
        parse_mode="HTML"
    )

@dp.message(F.forum_topic_created)
async def handle_topic_created(message: Message):
    topic = message.forum_topic_created
    if not topic or not topic.name:
        return
    name_lower = topic.name.lower()
    if "виїзд" in name_lower:
        from src.database import add_monitored_topic
        add_monitored_topic(message.chat.id, message.message_thread_id, "trips", topic.name)
        await message.reply(
            f"🚗 Гілку <b>{escape_html(topic.name)}</b> (ID: <code>{message.message_thread_id}</code>) "
            f"автоматично підключено до моніторингу виїздів та повернень!",
            parse_mode="HTML"
        )

@dp.message(F.forum_topic_edited)
async def handle_topic_edited(message: Message):
    topic = message.forum_topic_edited
    if not topic or not topic.name:
        return
    name_lower = topic.name.lower()
    from src.database import add_monitored_topic
    if "виїзд" in name_lower:
        add_monitored_topic(message.chat.id, message.message_thread_id, "trips", topic.name)


# AI-powered group chat message handler

@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, ~F.text.startswith("/"))
async def handle_group_text(message: Message):
    """
    Analyze free-text messages in group chats using AI (Google Gemini)
    to detect status change intents and automatically update employee status.
    In forum supergroups, only monitors the designated 'Виїзди' (trips) topic.
    """
    user = message.from_user
    if not user or not message.text:
        return

    chat_id = message.chat.id
    is_forum = getattr(message.chat, "is_forum", False) or (message.message_thread_id is not None)
    thread_id = get_effective_thread_id(message)

    from src.database import is_topic_monitored, has_monitored_topics
    is_trips = is_topic_monitored(chat_id, thread_id, "trips")
    is_main = is_topic_monitored(chat_id, thread_id, "main")
    print(f"[group_text] chat={chat_id} raw_thread={message.message_thread_id} "
          f"thread={thread_id} is_forum={is_forum} main={is_main} trips={is_trips}")

    # In a forum supergroup (or a chat with configured topics),
    # do NOT process messages outside the monitored 'trips' or 'main' topic
    if (is_forum or has_monitored_topics(chat_id, "main") or has_monitored_topics(chat_id, "trips")) and not (is_trips or is_main):
        return

    from src.nlp import analyze_message, format_note, get_client
    if not get_client():
        return  # AI analysis disabled — no API key configured

    from src.database import get_current_status, get_valid_actions, record_event

    # Get current status
    current_status = get_current_status(user.id)
    status = current_status.get("status") if current_status else "offline"

    # Check if this message is a reply to another message
    reply_text = None
    if message.reply_to_message and message.reply_to_message.text:
        reply_text = message.reply_to_message.text

    # Send message to AI for analysis
    result = await analyze_message(
        text=message.text,
        current_status=status,
        is_trips_topic=is_trips,
        reply_text=reply_text,
    )
    if not result:
        return  # Not a status-related message — ignore silently

    action = result["action"]
    includes_sender = result.get("includes_sender", True)
    mentioned_users = result.get("mentioned_users", [])
    is_plural = result.get("is_plural", False)

    from src.database import get_all_statuses, upsert_employee, get_employee
    all_employees = get_all_statuses()

    # Check if sender is registered in the employee/volunteer database
    sender_emp = get_employee(user.id)

    target_users = []
    matched_mentions = set()

    if includes_sender and sender_emp:
        target_users.append({
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name or "",
            "status": status,
        })

    if mentioned_users:
        for mention in mentioned_users:
            m_clean = normalize_name(mention)
            if len(m_clean) < 2:
                continue

            for emp in all_employees:
                emp_first = normalize_name(emp.get("first_name", ""))
                emp_last = normalize_name(emp.get("last_name") or "")
                emp_username = normalize_name(emp.get("username") or "")
                emp_aliases = [normalize_name(a) for a in (emp.get("aliases") or "").split(",") if a.strip()]

                match = False
                if emp_username and (m_clean == emp_username or m_clean in emp_username):
                    match = True
                elif emp_first and (m_clean == emp_first or m_clean in emp_first or emp_first in m_clean):
                    match = True
                elif emp_last and (m_clean == emp_last or m_clean in emp_last or emp_last in m_clean):
                    match = True
                else:
                    for alias in emp_aliases:
                        if m_clean == alias or m_clean in alias or alias in m_clean:
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
                    matched_mentions.add(mention)
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
    kyiv_time = datetime.now(KYIV_TZ)
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

    unmatched = [m for m in mentioned_users if m not in matched_mentions]
    if unmatched:
        msg += f"\n<i>ℹ️ Не зареєстровано в системі: {', '.join(escape_html(m) for m in unmatched)}</i>"

    await message.reply(msg, parse_mode="HTML")

# Fallback handler for private text messages

@dp.message(F.chat.type == "private", F.text)
async def fallback_private(message: Message):
    keyboard = build_private_keyboard(WEBAPP_URL)
    await message.reply(
        "Використовуйте кнопки на клавіатурі внизу екрана для взаємодії з системою.",
        reply_markup=keyboard,
    )

