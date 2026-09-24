import asyncio
import csv
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from telethon import TelegramClient
from telethon.errors import FloodWaitError

# --- НАСТРОЙКИ ---
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
SESSION_NAME = str(BASE_DIR / "test_history_session")
DEFAULT_CSV_FILE = "test_history_data.csv"
REQUIRED_ENV_VARIABLES = (
    "API_ID",
    "API_HASH",
    "BOT_TOKEN",
    "MY_CHAT_ID",
    "TARGET_GROUPS",
)


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    bot_token: str
    my_chat_id: int
    target_groups: tuple[str, ...]
    csv_file: Path


def load_env_file():
    """Загружает локальный .env, не заменяя уже заданные переменные."""
    if not ENV_FILE.is_file():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(name, value)


def load_settings():
    values = {
        name: os.getenv(name, "").strip()
        for name in REQUIRED_ENV_VARIABLES
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Не заданы переменные окружения: {names}")

    try:
        api_id = int(values["API_ID"])
        my_chat_id = int(values["MY_CHAT_ID"])
    except ValueError as error:
        raise ValueError("API_ID и MY_CHAT_ID должны быть целыми числами") from error

    if api_id <= 0:
        raise ValueError("API_ID должен быть положительным числом")

    target_groups = tuple(
        group.strip() for group in values["TARGET_GROUPS"].split(",") if group.strip()
    )
    if not target_groups:
        raise ValueError("TARGET_GROUPS должен содержать хотя бы одну группу")

    csv_file = Path(os.getenv("CSV_FILE", DEFAULT_CSV_FILE)).expanduser()
    return Settings(
        api_id=api_id,
        api_hash=values["API_HASH"],
        bot_token=values["BOT_TOKEN"],
        my_chat_id=my_chat_id,
        target_groups=target_groups,
        csv_file=csv_file,
    )


# ------------------

def send_via_bot(text, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        print(f"Ошибка отправки через бота: {error}")
        return False


def save_to_csv(csv_file, group_title, date, msg_id, sender_id, sender_name, text, matched_keyword):
    file_exists = csv_file.is_file()
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with csv_file.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow([
                "Группа", "Дата", "ID Сообщения", "ID Автора",
                "Имя автора", "Текст сообщения", "Найдено слово",
            ])
        writer.writerow([
            group_title, date, msg_id, sender_id, sender_name, text,
            matched_keyword,
        ])


def get_message_text(message):
    return message.text or message.caption or ""


def as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

async def scan_group(client, group_url, time_threshold, search_keyword, settings):
    print(f"Проверяю историю в: {group_url}...")
    group_title = group_url

    try:
        group = await client.get_entity(group_url)
        group_title = getattr(group, "title", None) or group_url
        group_username = getattr(group, "username", None)

        async for message in client.iter_messages(group, limit=300):
            message_date = as_utc(message.date)
            if message_date < time_threshold:
                break

            message_text = get_message_text(message)
            if not message_text or search_keyword not in message_text.lower():
                continue

            # Небольшая пауза при чтении, чтобы не создавать лишнюю нагрузку.
            await asyncio.sleep(0.1)

            sender_user = await message.get_sender()
            sender_name = " ".join(
                name for name in (
                    getattr(sender_user, "first_name", ""),
                    getattr(sender_user, "last_name", ""),
                ) if name
            ).strip()
            username = getattr(sender_user, "username", None)
            if not sender_name:
                sender_name = username or "Скрыто"
            sender_username = f"@{username}" if username else "Нет юзернейма"
            sender_id = message.sender_id or "Неизвестно"
            date_str = f"{message_date.strftime('%Y-%m-%d %H:%M:%S')} UTC"
            message_link = (
                f"https://t.me/{group_username}/{message.id}"
                if group_username else "Ссылка недоступна"
            )

            save_to_csv(
                settings.csv_file, group_title, date_str, message.id,
                sender_id, sender_name, message_text, search_keyword,
            )
            notification_text = (
                "🧪 ТЕСТ ИСТОРИИ\n"
                f"Найдено слово: {search_keyword}\n\n"
                f"Группа: {group_title}\n"
                f"Автор: {sender_name} ({sender_username})\n"
                f"Дата поста: {date_str}\n"
                f"Ссылка: {message_link}\n\n"
                f"Текст:\n{message_text}"
            )
            print(" -> Найдено совпадение! Отправляю ботом...")
            send_via_bot(notification_text, settings.bot_token, settings.my_chat_id)
            await asyncio.sleep(1)

        print(f"Завершена проверка группы {group_title}\n")
        await asyncio.sleep(5)
    except FloodWaitError as error:
        print(f"⚠️ Telegram попросил подождать {error.seconds} секунд.")
        await asyncio.sleep(error.seconds)
    except Exception as error:
        print(f"❌ Ошибка при работе с {group_url}: {error}\n")


async def main():
    load_env_file()
    try:
        settings = load_settings()
    except ValueError as error:
        print(f"Ошибка конфигурации: {error}")
        return

    search_keyword = input("Введите ключевое слово для теста истории: ").strip().lower()
    if not search_keyword:
        print("Ключевое слово не может быть пустым!")
        return

    time_threshold = datetime.now(timezone.utc) - timedelta(days=2)
    print(
        f"Ищу сообщения со словом '{search_keyword}' начиная с: "
        f"{time_threshold.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    )

    async with TelegramClient(SESSION_NAME, settings.api_id, settings.api_hash) as client:
        for group_url in settings.target_groups:
            await scan_group(
                client, group_url, time_threshold, search_keyword, settings,
            )

    print("Тестовый сбор истории за 2 суток завершен!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
