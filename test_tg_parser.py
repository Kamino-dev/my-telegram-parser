import csv
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tg_parser import (
    as_utc,
    get_message_text,
    load_settings,
    save_to_csv,
    send_via_bot,
)


class TelegramParserTests(unittest.TestCase):
    def test_get_message_text_supports_captions(self):
        message = SimpleNamespace(text=None, caption="Текст подписи")
        self.assertEqual(get_message_text(message), "Текст подписи")

    def test_as_utc_adds_timezone_to_naive_datetime(self):
        result = as_utc(datetime(2026, 9, 24, 12, 0, 0))
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_save_to_csv_writes_header_and_row(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_file = Path(directory) / "result.csv"
            save_to_csv(
                csv_file, "Группа", "2026-09-24 12:00:00 UTC", 1, 2,
                "Автор", "Нужное сообщение", "слово",
            )

            with csv_file.open(encoding="utf-8", newline="") as file:
                rows = list(csv.reader(file))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], "Группа")
            self.assertEqual(rows[1][-1], "слово")

    @patch("tg_parser.requests.post")
    def test_send_via_bot_uses_telegram_api_and_timeout(self, post):
        post.return_value = Mock()

        self.assertTrue(send_via_bot("сообщение", "test-token", 123))
        post.assert_called_once()
        url = post.call_args.args[0]
        self.assertEqual(url, "https://api.telegram.org/bottest-token/sendMessage")
        self.assertEqual(post.call_args.kwargs["json"], {"chat_id": 123, "text": "сообщение"})
        self.assertEqual(post.call_args.kwargs["timeout"], 15)
        post.return_value.raise_for_status.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "API_ID": "12345",
            "API_HASH": "hash",
            "BOT_TOKEN": "token",
            "MY_CHAT_ID": "123",
            "TARGET_GROUPS": "group_one, https://t.me/group_two",
            "CSV_FILE": "history.csv",
        },
        clear=True,
    )
    def test_load_settings_parses_groups(self):
        settings = load_settings()
        self.assertEqual(settings.api_id, 12345)
        self.assertEqual(settings.target_groups, ("group_one", "https://t.me/group_two"))
        self.assertEqual(settings.csv_file, Path("history.csv"))


if __name__ == "__main__":
    unittest.main()
