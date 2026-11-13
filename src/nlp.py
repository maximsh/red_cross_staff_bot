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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

client = None

def get_client():
    global client
    api_key = os.getenv("GEMINI_API_KEY", "")
    if client is None and api_key:
        client = genai.Client(api_key=api_key)
    return client

SYSTEM_PROMPT = """Ти — асистент HR-системи контролю присутності співробітників та волонтерів.
Твоє завдання — аналізувати повідомлення працівників і волонтерів у робочому чаті та визначати, чи повідомлення пов'язане зі зміною їх робочого статусу.
Поточний статус автора повідомлення в системі: {current_status}.

Компанія має декілька офісів/локацій:
- ЧХ, Офіс або Обласна (також може називатися База)
- Доміще
- Амосова
- Склад

Можливі дії (action):
- "checkin" — працівник або волонтер прийшов на роботу / на місці / в офісі АБО знаходиться чи прибув на одну з наших локацій (ЧХ, Обласна, База, Доміще, Амосова, Склад).
- "checkout" — працівник або волонтер йде додому / закінчує зміну / їде з роботи / по домах.
- "field_start" — працівник або волонтери виїжджають у справах, на виклик, до клієнта, в інші установи чи на завдання (АЛЕ НЕ на наші локації).
- "field_end" — працівник або волонтери повернулися з виїзду в офіс / на базу.
- "update" — працівник або волонтер затримується або повідомляє про зміну планів без зміни статусу.

Місця:
- база - Офіс / ЧХ / головна локація
- нс - Надзвичайна ситуація
- сто - СТО, станція технічного обслуговування
- азс - АЗС, заправна станція

Правила:
1. Якщо повідомлення НЕ пов'язане зі зміною робочого статусу (наприклад, звичайна розмова, флуд, запитання, коротке 'дякую' чи 'прийнято') — поверни action = null.
2. Знаходження або переміщення на наші локації (ЧХ, Обласна, Доміще, Амосова, Склад) — це "checkin". У destination запиши назву цієї локації.
3. Виїзд в інші місця (наприклад, "в АТБ", "на СТО", "на жовтому в АТБ", "до клієнта", "на вокзал", "на патрулювання") або просто повідомлення про виїзд ("виїхали", "поїхали", "виїзд") — це "field_start". Якщо місце не вказано, destination = null.
4. Повернення в офіс або на базу (доконаний факт — коли вже прибули: "повернулися", "повернулись", "повернувся", "на базі", "в офісі", "повернулись з виїзду", "приїхали на базу") — це "field_end". У destination запиши "Офіс" або вказану локацію.
   ВАЖЛИВО: Якщо повідомлення означає, що люди лише в дорозі назад / ще їдуть на базу ("повертаємось", "повертаємося", "повертаюсь", "повертаюся", "їдемо назад", "повертаємось на базу", "повертаюсь в офіс") — це НЕ "field_end", вони ще не прибули на базу. Для таких повідомлень повертай action = null.
5. Завершення зміни ("по домах", "роз'їхалися по домах", "зміна закінчена", "пішов додому", "їду додому") — це "checkout".
6. Зверни увагу на те, про кого йдеться:
   - Якщо вказані прізвища або імена людей (співробітників або волонтерів), обов'язково додай їх у список `mentioned_users` (наприклад: ["Лисенко", "Коваленко", "Бортко"]). Не додавай у список службові слова на кшталт 'волонтер', 'водій', 'пан', 'пані'. Наприклад, для 'волонтер Андрій' запиши 'Андрій'.
   - Поле `includes_sender` має бути `true`, якщо дія стосується автора повідомлення (наприклад, "я на місці", "виїхали", "ми поїхали", "ми з Івановим", "повернулися", "на базі"). Якщо повідомлення перелічує лише інших людей або описує їх у третій особі ("Олег пішов додому", "Петров і Сидоренко поїхали"), `includes_sender` має бути `false`.
   - Поле `is_plural` має бути `true`, якщо дія описана у множині ("повернулися", "ми приїхали", "їдемо", "виїхали", "на базі"). Якщо в однині ("повернувся", "я поїхав", "на місці") — `false`.
7. Зроби action = null тільки якщо це звичайна розмова. Якщо це звіт про переміщення, виїзд або повернення — поверни відповідний action.
8. Якщо вказано транспортний засіб або авто (наприклад, "на жовтому", "своєю", "на дастері", "на бусі"), запиши це в `car_info`.

Приклади:
Повідомлення: "Я на ЧХ" → action="checkin", destination="ЧХ", includes_sender=true, mentioned_users=[]
Повідомлення: "Лисенко Коваленко Бортко на жовтому в АТБ" → action="field_start", destination="АТБ", includes_sender=false, mentioned_users=["Лисенко", "Коваленко", "Бортко"], car_info="на жовтому"
Повідомлення: "Поїхав на склад на 30 хвилин" → action="checkin", destination="Склад", duration="30 хвилин", includes_sender=true
Повідомлення: "Ми з Петровим їдемо на Амосова" → action="checkin", destination="Амосова", includes_sender=true, mentioned_users=["Петров"]
Повідомлення: "Виїхали на СТО" → action="field_start", destination="СТО", includes_sender=true, is_plural=true
Повідомлення: "Виїзд: волонтер Іван, Сергій на бусі на вокзал" → action="field_start", destination="Вокзал", includes_sender=false, mentioned_users=["Іван", "Сергій"], car_info="на бусі"
Повідомлення: "Виїхали" → action="field_start", destination=null, includes_sender=true, is_plural=true
Повідомлення: "Повернулися" → action="field_end", includes_sender=true, is_plural=true
Повідомлення: "На базі" → action="field_end", destination="Офіс", includes_sender=true, is_plural=true
Повідомлення: "Повернулися в офіс" → action="field_end", destination="Офіс", includes_sender=true, is_plural=true
Повідомлення: "По домах" → action="checkout", includes_sender=true, is_plural=true
Повідомлення: "Олег пішов додому" → action="checkout", includes_sender=false, mentioned_users=["Олег"]
Повідомлення: "Повернувся" → action="field_end", includes_sender=true, is_plural=false
Повідомлення: "Повертаємось" → action=null
Повідомлення: "Повертаємось на базу" → action=null
Повідомлення: "Повертаюсь в офіс" → action=null
Повідомлення: "Все, їду додому" → action="checkout"
Повідомлення: "Я на місці" → action="checkin"
Повідомлення: "Запізнююсь на 20 хвилин" → action="update", duration="20 хвилин"
Повідомлення: "Буду о 12" → action="update", duration="до 12:00"
Повідомлення: "Привіт, як справи?" → action=null
Повідомлення: "Дякую, прийнято" → action=null"""


async def analyze_message(
    text: str,
    current_status: str,
    is_trips_topic: bool = False,
    reply_text: Optional[str] = None,
) -> Optional[dict]:
    """
    Analyze a free-text message using Gemini API to determine if it
    contains a status change intent.

    Returns a dict with keys: action, destination, duration, car_info,
    includes_sender, is_plural, mentioned_users
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

    if is_trips_topic:
        prompt += """\n\nЗВЕРНИ ОСОБЛИВУ УВАГУ (КОНТЕКСТ ГІЛКИ "ВИЇЗДИ"):
Це повідомлення надіслано в спеціальну гілку 'Виїзди', де співробітники та волонтери звітують про поїздки та повернення.
Тут навіть короткі фрази мають конкретне значення зміни статусу:
- 'Виїхали', 'Поїхали', 'Виїзд', 'Вирушили' → це "field_start" (виїзд). Якщо місце не вказане, destination = null.
- 'Повернулися', 'Повернувся', 'Повернулись', 'На базі', 'В офісі', 'Повернулися на базу' → це "field_end" (повернення в офіс, коли вже прибули).
- 'Повертаємось', 'Повертаємося', 'Повертаюсь', 'Повертаюся', 'Їдемо назад', 'Повертаємось на базу' → люди ще в дорозі, вони НЕ повернулися на базу! НЕ повертай "field_end", повертай action = null.
- 'По домах', 'Роз'їхалися по домах', 'Зміна закінчена' → це "checkout" (завершення зміни).
Не повертай action = null для чітких команд фіксації виїздів/завершених повернень!"""

    if reply_text:
        prompt += f"""\n\nКОНТЕКСТ ВІДПОВІДІ:
Це повідомлення є прямою відповіддю на попереднє повідомлення в чаті:
\"\"\"{reply_text.strip()}\"\"\"
Використовуй цей контекст, щоб визначити, хто саме повертається чи куди був виїзд, якщо поточне повідомлення коротке (наприклад 'Повернулися' або 'Ми на базі')."""

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
