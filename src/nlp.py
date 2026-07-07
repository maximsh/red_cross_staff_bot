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
- ЧХ або Обласна
- Доміше 
- Амосова 
- Склад

Можливі дії:
- "checkin" — працівник прийшов на роботу / на місці / в офісі АБО знаходиться на одній з локацій (ЧХ, Обласна, Доміше, Амосова, Склад).
- "checkout" — працівник йде додому / закінчує зміну / їде з роботи
- "field_start" — працівник виїжджає у справах, до клієнта, в інші установи (АЛЕ НЕ на наші локації).
- "field_end" — працівник повернувся з виїзду
- "update" — працівник затримується або повідомляє про зміну планів без зміни статусу

Поточний статус працівника: "{current_status}"
Допустимі переходи:
- З "offline" → можна: checkin, field_start, update
- З "in_office" → можна: checkout, field_start, update, checkin
- З "field_trip" → можна: field_end, checkout, update, checkin

Правила:
1. Якщо повідомлення НЕ пов'язане зі зміною робочого статусу — поверни action = null.
2. ВАЖЛИВО: Будь-яке переміщення або знаходження на локаціях (ЧХ, Обласна, Доміше, Амосова, Склад) — це дія "checkin", щоб система вважала працівника на роботі. У поле "destination" обов'язково запиши назву цієї локації.
3. Якщо працівник їде по справах НЕ на наші локації — це "field_start".
4. Якщо повідомлення пов'язане зі статусом — визнач дію, місце призначення (якщо є) та приблизну тривалість.
5. Дія повинна бути допустимою для поточного статусу. Якщо ні — поверни action = null.

Приклади:
Повідомлення: "Я на ЧХ" → action="checkin", destination="ЧХ"
Повідомлення: "Поїхав на склад на 30 хвилин" → action="checkin", destination="Склад", duration="30 хвилин"
Повідомлення: "Їду на Амосова" → action="checkin", destination="Амосова"
Повідомлення: "Буду на Обласній" → action="checkin", destination="Обласна"
Повідомлення: "Їду до клієнта, буду годину" → action="field_start", destination="до клієнта", duration="1 година"
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

        return {
            "action": action,
            "destination": dest if dest and dest != "null" else None,
            "duration": dur if dur and dur != "null" else None,
        }

    except json.JSONDecodeError as e:
        print(f"NLP JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"NLP Gemini API error: {e}")
        return None


def format_note(destination: Optional[str], duration: Optional[str]) -> str:
    """Format destination and duration into a human-readable note string."""
    parts = []
    if destination and destination != "null":
        parts.append(f"📍 {destination}")
    if duration and duration != "null":
        parts.append(f"≈{duration}")
    return " ".join(parts) if parts else ""
