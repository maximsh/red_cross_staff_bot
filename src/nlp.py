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

Можливі дії:
- "checkin" — працівник прийшов на роботу / на місці / в офісі
- "checkout" — працівник йде додому / закінчує зміну / їде з роботи
- "field_start" — працівник виїжджає кудись у справах (на склад, до клієнта, в податкову, тощо)
- "field_end" — працівник повернувся з виїзду / повернувся в офіс
- "update" — працівник затримується або повідомляє про зміну планів без зміни статусу (наприклад, "буду пізніше", "запізнююсь на 20 хв", "ще на годину")

Поточний статус працівника: "{current_status}"
Допустимі переходи:
- З "offline" → можна: checkin, field_start, update
- З "in_office" → можна: checkout, field_start, update
- З "field_trip" → можна: field_end, checkout, update

Правила:
1. Якщо повідомлення НЕ пов'язане зі зміною робочого статусу (привітання, питання, обговорення, їжа, тощо) — поверни action = null.
2. Якщо повідомлення пов'язане зі статусом — визнач дію, місце призначення (якщо є) та приблизну тривалість (якщо вказана).
3. Дія повинна бути допустимою для поточного статусу. Якщо дія не допустима — поверни action = null.
4. Розумій повідомлення з помилками, скороченнями та сленгом.

Приклади:
Повідомлення: "Поїхав на склад на 30 хвилин" → action="field_start", destination="склад", duration="30 хвилин"
Повідомлення: "Їду в податкову, буду годину" → action="field_start", destination="податкова", duration="1 година"
Повідомлення: "Повернувся" → action="field_end"
Повідомлення: "Я на місці" → action="checkin"
Повідомлення: "Все, їду додому" → action="checkout"
Повідомлення: "Запізнююсь на 20 хвилин" → action="update", duration="20 хвилин"
Повідомлення: "Буду о 12" → action="update", duration="до 12:00"
Повідомлення: "Привіт, як справи?" → action=null
Повідомлення: "Хто буде обідати?" → action=null
Повідомлення: "Я обідаю" → action=null
Повідомлення: "Добре, зроблю" → action=null"""


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

        return {
            "action": action,
            "destination": result.get("destination") or None,
            "duration": result.get("duration") or None,
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
    if destination:
        parts.append(f"📍 {destination}")
    if duration:
        parts.append(f"≈{duration}")
    return " ".join(parts) if parts else ""
