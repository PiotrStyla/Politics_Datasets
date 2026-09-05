import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("build_common_voice_pl.py")
SPEC = importlib.util.spec_from_file_location("build_common_voice_pl", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CommonVoiceTextTest(unittest.TestCase):
    def test_normalization_and_dedup_key(self):
        self.assertEqual(MODULE.normalize_text("  Za\u00a0dużo   spacji. "), "Za dużo spacji.")
        self.assertEqual(MODULE.dedup_key("To samo!"), MODULE.dedup_key("to samo."))

    def test_quality_filter_rejects_direct_pii_patterns(self):
        self.assertEqual(MODULE.quality_rejection("Napisz na a@example.com jutro."), "email")
        self.assertEqual(MODULE.quality_rejection("Zadzwoń pod numer 501 502 503."), "phone_like")
        self.assertEqual(MODULE.quality_rejection("Mój PESEL to 44051401458."), "pesel_like")

    def test_quality_filter_accepts_ordinary_polish_sentence(self):
        self.assertIsNone(MODULE.quality_rejection("Jutro pójdziemy razem do biblioteki."))

    def test_registry_update_is_scoped_and_idempotent(self):
        registry = 'SOURCES = {\n    "global_voices": {\n        "file_key": "global_voices",\n    },\n}\n'
        updated = MODULE.update_registry(registry)
        self.assertIn('"common_voice_pl": {', updated)
        self.assertEqual(MODULE.update_registry(updated), updated)


if __name__ == "__main__":
    unittest.main()
