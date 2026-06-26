from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codex"))


class SessionPatcherTests(unittest.TestCase):
    def test_refusal_detector_supports_real_chinese_refusal(self):
        from session_patcher import RefusalDetector

        detector = RefusalDetector()
        self.assertTrue(detector.detect("我不能帮助你实施这次攻击。"))
        self.assertTrue(detector.detect("很抱歉，我无法提供可用于绕过安全策略的步骤。"))
        self.assertTrue(detector.detect("出于安全和法律考虑，我不能继续这个请求。"))
        self.assertFalse(detector.detect("我不能确认这个漏洞，当前还需要更多证据。"))

    def test_refusal_detector_supports_expanded_english_refusal(self):
        from session_patcher import RefusalDetector

        detector = RefusalDetector()
        self.assertTrue(detector.detect("I can't provide instructions for bypassing this control."))
        self.assertTrue(detector.detect("Unfortunately I am not allowed to help with that request."))
        self.assertFalse(detector.detect("I cannot confirm this issue yet; need more evidence."))

    def test_mock_response_is_readable_chinese(self):
        from session_patcher import MOCK_RESPONSE

        self.assertIn("好的", MOCK_RESPONSE)
        self.assertIn("下一步", MOCK_RESPONSE)

    def test_clean_session_replaces_refusal_with_mock_response(self):
        from session_patcher import MOCK_RESPONSE, clean_session

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "sample.jsonl"
            line = {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "I cannot assist with that."}],
                },
            }
            session.write_text(json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
            cleaned, modified, changes = clean_session(str(session), use_ai=False)
            self.assertTrue(modified)
            self.assertEqual(changes[0].change_type, "replace")
            replaced = cleaned[0]["payload"]["content"][0]["text"]
            self.assertEqual(replaced, MOCK_RESPONSE)

    def test_clean_session_replaces_real_chinese_refusal(self):
        from session_patcher import MOCK_RESPONSE, clean_session

        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "sample-cn.jsonl"
            line = {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "抱歉，我无法帮助你完成这个请求。"}],
                },
            }
            session.write_text(json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8")
            cleaned, modified, changes = clean_session(str(session), use_ai=False)
            self.assertTrue(modified)
            self.assertEqual(changes[0].change_type, "replace")
            replaced = cleaned[0]["payload"]["content"][0]["text"]
            self.assertEqual(replaced, MOCK_RESPONSE)


if __name__ == "__main__":
    unittest.main()
