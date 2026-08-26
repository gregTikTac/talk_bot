import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from talking_bot.db.models import MessageDirection


class ParsedMessage(BaseModel):
    tg_message_id: int
    direction: MessageDirection
    text: str
    sent_at: datetime


def _extract_text(raw_text) -> str:
    """
    В экспорте Telegram Desktop поле "text" бывает либо строкой, либо
    списком кусков (обычный текст вперемешку с {"type": "bold", ...},
    {"type": "link", ...} и т.д. — так кодируется форматирование и
    упоминания). Достаём только читаемый текст, форматирование не нужно —
    guard и compose работают с обычным текстом.
    """
    if isinstance(raw_text, str):
        return raw_text
    if isinstance(raw_text, list):
        parts = []
        for chunk in raw_text:
            if isinstance(chunk, str):
                parts.append(chunk)
            elif isinstance(chunk, dict) and "text" in chunk:
                parts.append(chunk["text"])
        return "".join(parts)
    return ""


def parse_export(file_path: Path, my_from_id: str) -> list[ParsedMessage]:
    """
    my_from_id — значение поля "from_id" твоих собственных сообщений в
    экспорте (например "user361963836"). Им отличаем исходящие от входящих —
    в экспорте личного чата это единственный надёжный признак направления.

    Сообщения без текста (только фото/файл/видео) и служебные записи
    ("service") пропускаются — сейчас работаем только с текстом, вложения
    отдельная задача, не тянем её сюда неявно.
    """
    data = json.loads(file_path.read_text(encoding="utf-8"))

    result: list[ParsedMessage] = []
    for raw in data.get("messages", []):
        if raw.get("type") != "message":
            continue

        text = _extract_text(raw.get("text", ""))
        if not text.strip():
            continue

        direction = (
            MessageDirection.OUT
            if raw.get("from_id") == my_from_id
            else MessageDirection.IN
        )

        sent_at = datetime.fromtimestamp(int(raw["date_unixtime"]), tz=timezone.utc)

        result.append(
            ParsedMessage(
                tg_message_id=raw["id"],
                direction=direction,
                text=text,
                sent_at=sent_at,
            )
        )

    return result
