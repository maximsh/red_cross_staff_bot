"""
AI-powered natural language message analyzer for HR status updates.
Uses Google Gemini API to classify free-text messages and extract
intent, destination, and duration.
"""

import os
import json
from typing import Optional
from google import genai

# Initialize Gemini client
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite"

client = None

def get_client():
    global client
    if client is None and GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY)
    return client

SYSTEM_PROMPT = """Ти — асистент HR-системи контролю присутності співробітників.
Твоє завдання — аналізувати повідомлення працівників у робочому чаті та визначати, чи повідомлення пов'язане зі зміною їх робочого статусу.

Компанія має декілька офісів/локацій:
- ЧХ, Офіс або Обласна
- Доміще
- Амосова
- Склад

Можливі дії (action):
- "checkin" — працівник прийшов на роботу / на місці / в офісі АБО знаходиться на одній з локацій (ЧХ, Обласна, Доміще, Амосова, Склад).
- "checkout" — працівник йде додому / закінчує зміну / їде з роботи.
- "field_start" — працівник виїжджає у справах, до клієнта, в інші установи (АЛЕ НЕ на наші локації).
- "field_end" — працівник повернувся з виїзду.
- "update" — працівник затримується або повідомляє про зміну планів без зміни статусу.

Місця:
- нс - Надзвичайна ситуація
- сто - СТО, станція технічного обслуговування
- азс - АЗЗС, заправна станція

Правила:
1. Якщо повідомлення НЕ пов'язане зі зміною робочого статусу — поверни action = null.
2. Знаходження або переміщення на наші локації (ЧХ, Обласна, Доміще, Амосова, Склад) — це "checkin". У destination запиши назву.
3. Виїзд в інші місця (наприклад, "в АТБ", "на жовтому в АТБ", "до клієнта") — це "field_start".
4. Зверни увагу на те, про кого йдеться:
   - Якщо вказані прізвища або імена людей (наприклад, "Лисенко Коваленко Бортко на жовтому в АТБ"), обов'язково додай їх у список `mentioned_users` (наприклад: ["Лисенко", "Коваленко", "Бортко"]).
   - Поле `includes_sender` має бути `true`, якщо дія стосується автора повідомлення (наприклад, "я на місці", "ми поїхали", "ми з Івановим"). Якщо повідомлення перелічує лише інших людей або всіх поіменно (включаючи автора в третій особі), `includes_sender` може бути `false`.
   - Поле `is_plural` має бути `true`, якщо дія описана у множині ("повернулися", "ми приїхали", "їдемо"). Якщо в однині ("повернувся", "я поїхав", "на місці") — `false`.
5. Зроби action = null тільки якщо це звичайна розмова. Якщо це звіт про переміщення, поверни відповідний action.
6. Якщо вказано транспортний засіб або авто (наприклад, "на жовтому", "своєю", "на дастері"), запиши це в `car_info`.

Приклади:
Повідомлення: "Я на ЧХ" → action="checkin", destination="ЧХ", includes_sender=true, mentioned_users=[]
Повідомлення: "Лисенко Коваленко Бортко на жовтому в АТБ" → action="field_start", destination="АТБ", includes_sender=false, mentioned_users=["Лисенко", "Коваленко", "Бортко"], car_info="на жовтому"
Повідомлення: "Поїхав на склад на 30 хвилин" → action="checkin", destination="Склад", duration="30 хвилин", includes_sender=true
Повідомлення: "Ми з Петровим їдемо на Амосова" → action="checkin", destination="Амосова", includes_sender=true, mentioned_users=["Петров"]
Повідомлення: "Олег пішов додому" → action="checkout", includes_sender=false, mentioned_users=["Олег"]
Повідомлення: "Повернувся" → action="field_end"
Повідомлення: "Все, їду додому" → action="checkout"
Повідомлення: "Я на місці" → action="checkin"
Повідомлення: "Запізнююсь на 20 хвилин" → action="update", duration="20 хвилин"
Повідомлення: "Буду о 12" → action="update", duration="до 12:00"
Повідомлення: "Привіт, як справи?" → action=null"""


async def analyze_message(text: str, current_status: str) -> Optional[dict]:
    """
    Analyze a free-text message using Gemini API to determine if it
    contains a status change intent.

    Returns a dict with keys: action, destination, duration
    or None if the message is not status-related or on error.
    """
    gemini = get_client()
    if not gemini:
        return None

    # Skip very short or very long messages
    stripped = text.strip()
    if len(stripped) < 2 or len(stripped) > 500:
        return None

    # Map internal status names to Ukrainian-readable for prompt context
    status_map = {
        "offline": "offline",
        "in_office": "in_office",
        "field_trip": "field_trip",
    }
    status_label = status_map.get(current_status, "offline")

    prompt = SYSTEM_PROMPT.format(current_status=status_label)

    response_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Дія, якщо вона стосується зміни статусу. null, якщо ні.",
                "enum": ["checkin", "checkout", "field_start", "field_end", "update"]
            },
            "destination": {
                "type": "string",
                "description": "Місце призначення, якщо вказано"
            },
            "duration": {
                "type": "string",
                "description": "Тривалість (наприклад, '30 хвилин', 'до 12:00')"
            },
            "includes_sender": {
                "type": "boolean",
                "description": "Чи стосується дія самого автора повідомлення."
            },
            "is_plural": {
                "type": "boolean",
                "description": "Чи дія описана у множині ('повернулися', 'ми приїхали'). Якщо в однині ('повернувся') — false."
            },
            "mentioned_users": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Список імен або прізвищ інших працівників, які вказані в повідомленні."
            },
            "car_info": {
                "type": "string",
                "description": "Інформація про автомобіль (наприклад, 'на жовтому', 'на Дастері', 'своєю'), якщо вказано."
            }
        }
    }

    try:
        response = await gemini.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=stripped,
            config=genai.types.GenerateContentConfig(
                system_instruction=prompt,
                temperature=0.1,
                max_output_tokens=150,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        response_text = response.text.strip()
        result = json.loads(response_text)

        # Validate response structure
        action = result.get("action")
        if not action or action not in ("checkin", "checkout", "field_start", "field_end", "update"):
            return None

        dest = result.get("destination")
        dur = result.get("duration")

        car = result.get("car_info")

        return {
            "action": action,
            "destination": dest if dest and dest != "null" else None,
            "duration": dur if dur and dur != "null" else None,
            "car_info": car if car and car != "null" else None,
            "includes_sender": result.get("includes_sender", True),
            "is_plural": result.get("is_plural", False),
            "mentioned_users": result.get("mentioned_users", []),
        }

    except json.JSONDecodeError as e:
        print(f"NLP JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"NLP Gemini API error: {e}")
        return None


def format_note(destination: Optional[str], duration: Optional[str], car_info: Optional[str] = None) -> str:
    """Format destination, duration, and car_info into a human-readable note string."""
    parts = []
    if destination and destination != "null":
        parts.append(f"📍 {destination}")
    if duration and duration != "null":
        parts.append(f"≈{duration}")
    if car_info and car_info != "null":
        parts.append(f"🚗 {car_info}")
    return " ".join(parts) if parts else ""
