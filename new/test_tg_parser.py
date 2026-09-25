import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError

# =====================================================================
# НАСТРОЙКИ ПАРСЕРА (Группы и Ключевые слова настраиваются здесь!)
# =====================================================================
TARGET_GROUPS = (
    "https://t.me",  # Ваша целевая группа
    # Сюда можно добавлять другие группы через запятую в кавычках
)

KEYWORDS = [
    "замена",
    "подработка",
    "работа",
    "срочно",
    # Сюда можно вписать любые другие слова в нижнем регистре
]
# =====================================================================

BASE_DIR = Path(__file__).resolve().parent
SESSION_NAME = str(BASE_DIR / "test_history_session")
REQUIRED_ENV_VARIABLES = ("API_ID", "API_HASH", "BOT_TOKEN", "MY_CHAT_ID")


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    bot_token: str
    my_chat_id: int


def load_settings():
    values = {name: os.getenv(name, "").strip() for name in REQUIRED_ENV_VARIABLES}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Не заданы секреты в GitHub Actions: {', '.join(missing)}")

    return Settings(
        api_id=int(values["API_ID"]),
        api_hash=values["API_HASH"],
        bot_token=values["BOT_TOKEN"],
        my_chat_id=int(values["MY_CHAT_ID"]),
    )


async def main():
    try:
        settings = load_settings()
    except ValueError as error:
        print(f"Ошибка конфигурации: {error}")
        return

    client = TelegramClient(SESSION_NAME, settings.api_id, settings.api_hash)
    await client.start()

    # Проверяем посты за последние 24 часа
    time_threshold = datetime.now(timezone.utc) - timedelta(days=1)
    print(f"Запуск парсинга по списку слов: {KEYWORDS}...")

    for group_url in TARGET_GROUPS:
        try:
            group = await client.get_entity(group_url)
            group_title = getattr(group, "title", None) or group_url
            group_username = getattr(group, "username", None)

            async for message in client.iter_messages(group, limit=200):
                if message.date.replace(tzinfo=timezone.utc) < time_threshold:
                    break

                text = message.text or message.caption or ""
                if not text:
                    continue

                # Проверяем, есть ли хотя бы одно слово из списка KEYWORDS в тексте сообщения
                text_lower = text.lower()
                matched_words = [word for word in KEYWORDS if word in text_lower]

                if not matched_words:
                    continue

                # Формируем красивую ссылку на пост, если есть юзернейм группы
                if group_username:
                    message_link = f"https://t.me{group_username}/{message.id}"
                    group_display = f"[{group_title}]({message_link})"
                else:
                    group_display = f"*{group_title}*"

                # Подсвечиваем найденные слова
                found_str = ", ".join(matched_words)

                # Создаем красивое сообщение с Markdown-разметкой
                notification_text = (
                    f"🔔 *НАЙДЕНО СОВПАДЕНИЕ*\n"
                    f"📍 *Группа:* {group_display}\n"
                    f"🔑 *Ключевые слова:* `{found_str}`\n\n"
                    f"📝 *Текст сообщения:*\n{text}"
                )

                # Отправляем сообщение с поддержкой Markdown форматирования (parse_mode='md')
                await client.send_message(
                    settings.my_chat_id, notification_text, parse_mode="md"
                )
                await asyncio.sleep(1)

        except FloodWaitError as e:
            print(f"Превышен лимит запросов Telegram. Ожидание {e.seconds} сек.")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            print(f"Ошибка при обработке {group_url}: {e}")

    await client.disconnect()
    print("Парсинг успешно завершен!")


if __name__ == "__main__":
    asyncio.run(main())
