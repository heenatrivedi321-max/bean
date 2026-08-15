"""bean's test suite — runs on macOS, Linux and Windows (CI matrix).

No real network, no real model downloads: everything external is stubbed.
The point is to prove the code paths are sound on every OS.
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bean
import catalog
import config
import onboard
import setup_wizard


class FakeConsole:
    def __init__(self):
        self.printed = []

    def print(self, *args, **kwargs):
        self.printed.append(args)

    def status(self, *args, **kwargs):
        class S:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False
        return S()

    def out(self, *args, **kwargs):
        pass

    def input(self, *args, **kwargs):
        return ""


class CloudPickTests(unittest.TestCase):
    def test_parse_recommendation_valid(self):
        text = '{"reply": "hi", "models": [{"name": "llama3.2:3b", "why": "x"}]}'
        rec = bean._parse_recommendation(text)
        self.assertEqual(rec["models"][0]["name"], "llama3.2:3b")

    def test_parse_recommendation_rejects_invented_models(self):
        text = '{"reply": "hi", "models": [{"name": "made-up:99b", "why": "x"}]}'
        self.assertIsNone(bean._parse_recommendation(text))

    def test_parse_recommendation_garbage(self):
        self.assertIsNone(bean._parse_recommendation("just chatting, no json"))
        self.assertIsNone(bean._parse_recommendation(""))

    def test_fallback_recommend(self):
        rec = bean.fallback_recommend("a python coding assistant", 8.0)
        self.assertTrue(rec["models"])
        for m in rec["models"]:
            self.assertIn(m["name"], {c["name"] for c in catalog.CATALOG})


class SetupLoopTests(unittest.TestCase):
    """The conversational setup must terminate: greet-chat forever is capped,
    and an empty Enter must re-prompt, not exit."""

    def setUp(self):
        bean.console = FakeConsole()

        def fake_proxy(conversation, budget):
            # Chat normally until the user states a need, then recommend.
            last = conversation[-1]["content"].lower() if conversation else ""
            if "writing" in last:
                return ('{"reply": "here you go", "models": ['
                        '{"name": "llama3.2:3b", "why": "x"}]}')
            return "Just chatting! What would you like a model to do?"

        bean.ask = mock.Mock(side_effect=iter(["hi"] * 20 + ["exit"]))
        bean.recommend_via_proxy = mock.Mock(side_effect=fake_proxy)
        bean.recommend = mock.Mock(return_value=None)
        bean.fallback_recommend = mock.Mock(return_value={
            "reply": "local", "models": [{"name": "llama3.2:3b", "why": "x"}]})
        bean.setup_wizard.model_present = mock.Mock(return_value=True)
        bean.onboard.save_profile = mock.Mock()
        bean.setup_wizard.free_stray_ram = mock.Mock(return_value=False)
        bean.onboard.ram_budget_gb = mock.Mock(return_value=8.0)
        bean.config.PROXY_URL = "https://example.workers.dev"
        bean.config.cloud_api_key = mock.Mock(return_value=None)

    def test_chat_loop_caps_at_twelve_turns(self):
        # 'hi' is never a need, so all 12 turns are chat — the cap falls
        # back to local matching instead of looping forever.
        profile = bean.setup_flow()
        self.assertIsNotNone(profile)
        self.assertEqual(profile["model"], "llama3.2:3b")
        self.assertEqual(bean.ask.call_count, 12)  # capped, no extra prompt

    def test_exit_returns_none(self):
        bean.ask = mock.Mock(side_effect=iter(["exit"]))
        self.assertIsNone(bean.setup_flow())

    def test_eof_returns_none_not_infinite_loop(self):
        # ask() returns None at EOF (Ctrl+D / closed pipe). The setup loop
        # must treat that as "finished", never loop forever.
        bean.ask = mock.Mock(return_value=None)
        self.assertIsNone(bean.setup_flow())

    def test_blank_enter_reprompts_but_eof_exits_chat(self):
        # chat(): "" (blank Enter) re-prompts, None (EOF) exits.
        import io
        from rich.console import Console as RichConsole
        real_console = bean.console
        bean.console = RichConsole(file=io.StringIO(), force_terminal=False)
        try:
            with mock.patch.object(bean, "ask",
                                   side_effect=iter(["", None])):
                bean.chat({"model": "llama3.2:3b"})  # must return, not hang
        finally:
            bean.console = real_console

    def test_empty_enter_reprompts_not_exits(self):
        bean.ask = mock.Mock(side_effect=iter(["", "", "a writing buddy", "exit"]))
        profile = bean.setup_flow()
        self.assertIsNotNone(profile)
        self.assertEqual(profile["model"], "llama3.2:3b")


class DownloadTests(unittest.TestCase):
    def test_download_success_parses_ansi_progress(self):
        # Real `ollama pull` output is ANSI cursor moves, not \r frames.
        ansi = (b"\x1b[A\x1b[1G\x1b[2K 12%\x1b[K\n\x1b[1G\x1b[2K 45%\x1b[K\n"
                b"\x1b[1G\x1b[2K 100%\x1b[K\n\x1b[1G\x1b[2K success\x1b[K\n")

        class FakeStderr(io.RawIOBase):
            def __init__(self, data):
                self.data = data
                self.pos = 0

            def read(self, n=-1):
                if self.pos >= len(self.data):
                    return b""
                chunk = self.data[self.pos:self.pos + n]
                self.pos += len(chunk)
                return chunk

        class FakeProc:
            stderr = FakeStderr(ansi)
            returncode = 0

            def wait(self):
                return 0

            def kill(self):
                pass

        with mock.patch("bean.subprocess.Popen", return_value=FakeProc()):
            self.assertTrue(bean.download("smollm2:135m"))

    def test_download_interrupt_returns_false(self):
        class BoomStderr(io.RawIOBase):
            def read(self, n=-1):
                raise KeyboardInterrupt

        class FakeProc:
            stderr = BoomStderr()
            returncode = None
            killed = False

            def kill(self):
                self.killed = True

            def wait(self):
                return 1

        with mock.patch("bean.subprocess.Popen", return_value=FakeProc()):
            self.assertFalse(bean.download("smollm2:135m"))


class HandoffTests(unittest.TestCase):
    """handoff_to_app must behave sensibly on every OS."""

    def setUp(self):
        bean.console = FakeConsole()
        bean.warm_model = mock.Mock()

    @unittest.skipUnless(sys.platform == "darwin", "macOS app path only")
    def test_darwin_app_present(self):
        with mock.patch("bean.Path.exists", return_value=True):
            with mock.patch("bean.subprocess.run") as run:
                run.return_value = None
                self.assertTrue(bean.handoff_to_app("llama3.2:3b"))

    @unittest.skipUnless(sys.platform == "darwin", "macOS app path only")
    def test_darwin_app_missing(self):
        with mock.patch("bean.Path.exists", return_value=False):
            self.assertFalse(bean.handoff_to_app("llama3.2:3b"))

    def test_linux_falls_back_to_workshop(self):
        with mock.patch.object(bean.sys, "platform", "linux"):
            self.assertFalse(bean.handoff_to_app("llama3.2:3b"))

    def test_win32_opens_ollama_scheme(self):
        calls = []

        def fake_startfile(url):
            calls.append(url)

        with mock.patch.object(bean.sys, "platform", "win32"):
            with mock.patch.object(bean.os, "startfile", fake_startfile, create=True):
                self.assertTrue(bean.handoff_to_app("llama3.2:3b"))
        self.assertEqual(calls, ["ollama://"])

    def test_win32_no_app_falls_back(self):
        def boom(url):
            raise OSError("no handler for ollama://")

        with mock.patch.object(bean.sys, "platform", "win32"):
            with mock.patch.object(bean.os, "startfile", boom, create=True):
                self.assertFalse(bean.handoff_to_app("llama3.2:3b"))


class ConfigTests(unittest.TestCase):
    def test_proxy_url_default(self):
        self.assertTrue(config.PROXY_URL)

    def test_profile_roundtrip(self):
        with mock.patch("onboard.PROFILE_PATH") as p:
            p.exists = mock.Mock(return_value=True)
            p.read_text = mock.Mock(return_value=json.dumps(
                {"need": "x", "models": ["llama3.2:3b"], "model": "llama3.2:3b"}))
            profile = onboard.load_profile()
            self.assertEqual(profile["model"], "llama3.2:3b")
        with mock.patch("onboard.config.ensure_dirs"):
            with mock.patch("onboard.PROFILE_PATH") as p:
                p.write_text = mock.Mock()
                onboard.save_profile({"need": "x", "models": ["llama3.2:3b"],
                                      "model": "llama3.2:3b"})
                p.write_text.assert_called_once()


class ModuleSmokeTests(unittest.TestCase):
    def test_catalog_integrity(self):
        names = [c["name"] for c in catalog.CATALOG]
        self.assertEqual(len(names), len(set(names)), "duplicate model names")
        for c in catalog.CATALOG:
            self.assertGreater(c["gb"], 0)
            self.assertTrue(c["uses"])

    def test_classify_known_uses(self):
        self.assertIn(catalog.classify("write an essay for me"),
                      ("writing", "general"))
        self.assertIn(catalog.classify("python coding help"),
                      ("coding", "general"))


if __name__ == "__main__":
    unittest.main(verbosity=2)