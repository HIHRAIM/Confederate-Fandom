"""Offline checks for file-import planning and overwrite behaviour."""
import hashlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scripts import importfiles
from tasks.dialog import decode_list_document
from telegram_bot.dialogs import TelegramConversation
from discord_bot.dialogs import DiscordConversation

class ImportFilesTests(unittest.TestCase):
    """Uploads use mocks: these tests never contact or edit a wiki."""

    def context(self, existing="skip", description="copy", dry_run=False):
        return types.SimpleNamespace(
            site=Mock(), wiki="test:en", reader="en", summary="Import test",
            params={"file_existing": existing, "file_description": description},
            state={"importfiles": {"session": Mock(), "api": "https://source.example/api.php"}},
            dry_run=dry_run,
        )

    @staticmethod
    def source_info(payload=b"new file"):
        return {"url": "https://source.example/file.png", "size": len(payload),
                "sha1": hashlib.sha1(payload).hexdigest(), "text": "Source description",
                "page_url": "https://source.example/wiki/File:Example.png"}

    def test_private_source_rejected(self):
        with self.assertRaises(ValueError):
            importfiles._public_https("http://source.example/wiki/Main_Page")
        with self.assertRaises(ValueError):
            importfiles._public_https("https://127.0.0.1/api.php")

    def test_text_file_list_is_bounded_utf8(self):
        self.assertEqual(decode_list_document("names.txt", b"\xef\xbb\xbfOne\nTwo"),
                         "One\nTwo")
        with self.assertRaises(ValueError):
            decode_list_document("names.txt", b"x" * (128 * 1024 + 1))
        with self.assertRaises(ValueError):
            decode_list_document("names.pdf", b"One")

    def test_category_members_deduplicate_across_categories(self):
        ctx = self.context()
        ctx.params.update(file_scope="categories", file_categories="Category:First\nSecond",
                          file_limit=3)
        calls = []

        def query(_session, _api, **params):
            calls.append(params)
            if params["cmtitle"] == "Category:First":
                return {"categorymembers": [{"title": "File:A.png"},
                                            {"title": "File:B.png"}]}
            if "cmcontinue" not in params:
                return {"categorymembers": [{"title": "File:B.png"}],
                        "_continue": {"cmcontinue": "next"}}
            return {"categorymembers": [{"title": "File:C.png"}]}

        with patch.object(importfiles, "_query", side_effect=query):
            self.assertEqual(importfiles.pages(ctx),
                             ["File:A.png", "File:B.png", "File:C.png"])
        self.assertEqual(len(calls), 3)

    def test_used_files_from_page_list(self):
        ctx = self.context()
        ctx.params.update(file_scope="pages", file_pages="First_page\nSecond page",
                          file_limit=3)

        def query(_session, _api, **params):
            if params["titles"] == "First page":
                return {"pages": [{"images": [{"title": "File:A.png"},
                                               {"title": "File:B.png"}]}]}
            if "imcontinue" not in params:
                return {"pages": [{"images": [{"title": "File:B.png"}]}],
                        "_continue": {"imcontinue": "next"}}
            return {"pages": [{"images": [{"title": "File:C.png"}]}]}

        with patch.object(importfiles, "_query", side_effect=query):
            self.assertEqual(importfiles.pages(ctx),
                             ["File:A.png", "File:B.png", "File:C.png"])

    def test_skip_existing_without_download(self):
        ctx = self.context()
        destination = Mock()
        destination.exists.return_value = True
        with patch("pywikibot.FilePage", return_value=destination), patch.object(
                importfiles, "_target_file_hash", return_value="old"), patch.object(
                importfiles, "_source_file") as source:
            state, _message = importfiles.act(ctx, Mock(title=lambda: "File:Example.png"))
        self.assertEqual(state, "skip")
        source.assert_not_called()
        destination.upload.assert_not_called()

    def test_overwrite_uses_narrow_warning_allowlist(self):
        ctx = self.context(existing="overwrite")
        destination = Mock()
        destination.exists.return_value = True
        destination.upload.return_value = True
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            temp.write(b"new file")
            path = temp.name
        with patch("pywikibot.FilePage", return_value=destination), patch.object(
                importfiles, "_target_file_hash", return_value="old"), patch.object(
                importfiles, "_source_file", return_value=self.source_info()), patch.object(
                importfiles, "_download", return_value=path), patch(
                "wiki.use_cookies"):
            state, _message = importfiles.act(ctx, Mock(title=lambda: "File:Example.png"))
        self.assertEqual(state, "done")
        self.assertFalse(os.path.exists(path))
        kwargs = destination.upload.call_args.kwargs
        self.assertEqual(kwargs["ignore_warnings"], ("exists", "page-exists"))
        self.assertFalse(kwargs["report_success"])
        self.assertEqual(kwargs["text"], "Source description")

    def test_same_binary_skips_reupload(self):
        ctx = self.context(existing="overwrite")
        destination = Mock()
        destination.exists.return_value = True
        destination.text = "Source description"
        info = self.source_info()
        with patch("pywikibot.FilePage", return_value=destination), patch.object(
                importfiles, "_target_file_hash", return_value=info["sha1"]), patch.object(
                importfiles, "_source_file", return_value=info):
            state, _message = importfiles.act(ctx, Mock(title=lambda: "File:Example.png"))
        self.assertEqual(state, "skip")
        destination.upload.assert_not_called()

    def test_same_binary_can_update_description_only(self):
        ctx = self.context(existing="overwrite")
        destination = Mock()
        destination.exists.return_value = True
        destination.text = "Previous description"
        info = self.source_info()
        with patch("pywikibot.FilePage", return_value=destination), patch.object(
                importfiles, "_target_file_hash", return_value=info["sha1"]), patch.object(
                importfiles, "_source_file", return_value=info), patch(
                "wiki.use_cookies"):
            state, _message = importfiles.act(ctx, Mock(title=lambda: "File:Example.png"))
        self.assertEqual(state, "done")
        self.assertEqual(destination.text, "Source description")
        destination.save.assert_called_once()
        destination.upload.assert_not_called()

class ListDialogTests(unittest.IsolatedAsyncioTestCase):
    """An attachment list is read only for the one question requesting it."""

    async def test_telegram_regular_answer_still_returns_text(self):
        conv = TelegramConversation.__new__(TelegramConversation)
        conv.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=1),
                                             answer=AsyncMock())
        conv.user_id = 2
        reply = types.SimpleNamespace(text="ordinary answer", caption=None)
        with patch("telegram_bot.dialogs.wait_for_message", new=AsyncMock(return_value=reply)):
            self.assertEqual(await conv.ask("Question"), "ordinary answer")

    async def test_telegram_document_list(self):
        conv = TelegramConversation.__new__(TelegramConversation)
        conv.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=1),
                                             answer=AsyncMock())
        conv.user_id = 2
        doc = types.SimpleNamespace(file_size=8, file_name="list.txt")
        reply = types.SimpleNamespace(document=doc)

        async def download(_document, destination):
            destination.write(b"A\nB")

        with patch("telegram_bot.dialogs.wait_for_message", new=AsyncMock(return_value=reply)), patch(
                "telegram_bot.client.bot.download", new=download):
            self.assertEqual(await conv.ask_text_or_file("List"), "A\nB")

    async def test_discord_attachment_list(self):
        conv = DiscordConversation.__new__(DiscordConversation)
        attachment = types.SimpleNamespace(size=3, filename="list.txt",
                                           read=AsyncMock(return_value=b"A\nB"))
        reply = types.SimpleNamespace(content="", attachments=[attachment])
        with patch.object(DiscordConversation, "_reply", new=AsyncMock(return_value=reply)):
            self.assertEqual(await conv.ask_text_or_file("List"), "A\nB")

if __name__ == "__main__":
    unittest.main()
