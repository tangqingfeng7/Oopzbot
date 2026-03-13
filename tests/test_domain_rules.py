import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class ProfanityRulesTest(unittest.TestCase):
    def test_match_keyword_is_case_insensitive(self) -> None:
        from domain.safety.profanity_rules import match_keyword

        self.assertEqual(match_keyword("Hello BAD world", ("bad", "evil")), "bad")
        self.assertIsNone(match_keyword("Hello world", ("bad", "evil")))

    def test_match_context_keyword_returns_latest_matching_window(self) -> None:
        from domain.safety.profanity_rules import match_context_keyword

        messages = ["今", "天很", "坏"]
        self.assertEqual(match_context_keyword(messages, ("今天很坏", "别的")), ("今天很坏", 0))
        self.assertEqual(match_context_keyword(["前文", "差", "一点"], ("一点",)), ("一点", 1))
        self.assertIsNone(match_context_keyword(["单条"], ("单条",)))

    def test_actual_mute_duration_uses_thresholds(self) -> None:
        from domain.safety.profanity_rules import actual_mute_duration

        self.assertEqual(actual_mute_duration(1), 1)
        self.assertEqual(actual_mute_duration(2), 5)
        self.assertEqual(actual_mute_duration(61), 1440)
        self.assertEqual(actual_mute_duration(20000), 10080)
        self.assertEqual(actual_mute_duration(7, thresholds=()), 7)

    def test_format_duration_outputs_human_readable_chinese(self) -> None:
        from domain.safety.profanity_rules import format_duration

        self.assertEqual(format_duration(5), "5 分钟")
        self.assertEqual(format_duration(120), "2 小时")
        self.assertEqual(format_duration(2880), "2 天")


class RoleRulesTest(unittest.TestCase):
    def test_resolve_role_id_by_id_or_name(self) -> None:
        from domain.community.role_rules import resolve_role_id

        roles = [
            {"roleID": 1, "name": "管理员"},
            {"roleID": "2", "name": "成员"},
        ]

        self.assertEqual(resolve_role_id(roles, "1"), 1)
        self.assertEqual(resolve_role_id(roles, "成员"), "2")
        self.assertIsNone(resolve_role_id(roles, "不存在"))
        self.assertIsNone(resolve_role_id(roles, ""))


class PublicCommandRulesTest(unittest.TestCase):
    def test_public_mention_prefixes_cover_expected_commands(self) -> None:
        from domain.routing.public_command_rules import is_public_mention_text

        self.assertTrue(is_public_mention_text("每日一句 来一条"))
        self.assertTrue(is_public_mention_text("帮助"))
        self.assertTrue(is_public_mention_text("help me"))
        self.assertTrue(is_public_mention_text("我的资料"))
        self.assertFalse(is_public_mention_text("管理员命令"))

    def test_public_slash_command_is_case_insensitive(self) -> None:
        from domain.routing.public_command_rules import is_public_slash_command

        self.assertTrue(is_public_slash_command("/HELP"))
        self.assertTrue(is_public_slash_command("/myinfo"))
        self.assertFalse(is_public_slash_command("/ban"))


if __name__ == "__main__":
    unittest.main()
