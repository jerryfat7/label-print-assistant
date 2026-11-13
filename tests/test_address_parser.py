"""Synthetic recipients only; never store real delivery details in this suite."""
import unittest

from webapp.address_parser import CpcaStrategy, RegexStrategy

PHONE_A = "138" + "0" * 8
PHONE_B = "139" + "0" * 8
ADDRESS_A = "湖北省武汉市汉阳区示例路1号"
ADDRESS_B = "浙江省杭州市西湖区示例街2号"


class WrappedAddressTests(unittest.TestCase):
    def parse(self, text):
        return RegexStrategy().parse_batch(text)

    def test_phone_and_address_on_separate_lines_are_one_recipient(self):
        items = self.parse(f"测试甲 {PHONE_A}\n{ADDRESS_A}")
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].name, items[0].phone, items[0].full_address),
                         ("测试甲", PHONE_A, ADDRESS_A))
        self.assertIsNone(items[0].parse_error)

    def test_multiline_batch_without_blank_separators(self):
        items = self.parse(f"测试甲 {PHONE_A}\n{ADDRESS_A}\n测试乙 {PHONE_B}\n{ADDRESS_B}")
        self.assertEqual([item.name for item in items], ["测试甲", "测试乙"])
        self.assertEqual([item.full_address for item in items], [ADDRESS_A, ADDRESS_B])
        self.assertEqual([item.index for item in items], [0, 1])

    def test_three_line_recipient_and_wrapped_building(self):
        items = self.parse(f"测试甲\n{PHONE_A}\n{ADDRESS_A}\n2单元3室")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].name, "测试甲")
        self.assertEqual(items[0].full_address, ADDRESS_A + " 2单元3室")

    def test_following_three_line_recipient_does_not_attach_name_to_previous(self):
        items = self.parse(f"测试甲 {PHONE_A} {ADDRESS_A}\n测试乙\n{PHONE_B}\n{ADDRESS_B}")
        self.assertEqual([item.name for item in items], ["测试甲", "测试乙"])
        self.assertEqual(items[0].full_address, ADDRESS_A)

    def test_single_line_batches_still_work(self):
        items = self.parse(f"测试甲 {PHONE_A} {ADDRESS_A}\r\n测试乙,{PHONE_B},{ADDRESS_B}")
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.parse_error is None for item in items))

    def test_outer_copy_brackets_are_removed_but_internal_address_brackets_remain(self):
        items = self.parse(f"（测试甲 {PHONE_A}\n{ADDRESS_A}（测试门））")
        self.assertEqual(items[0].name, "测试甲")
        self.assertEqual(items[0].full_address, ADDRESS_A + "（测试门）")

    def test_blank_lines_separate_records_and_invalid_lines_stay_visible(self):
        items = self.parse(f"测试甲 {PHONE_A} {ADDRESS_A}\n无法识别\n\n测试乙 {PHONE_B}\n{ADDRESS_B}")
        self.assertEqual(len(items), 3)
        self.assertIsNotNone(items[1].parse_error)
        self.assertEqual(items[2].name, "测试乙")

    def test_phone_like_substring_of_long_number_is_not_a_new_recipient(self):
        items = self.parse(f"测试甲 {PHONE_A} {ADDRESS_A}\n订单号 {PHONE_B}9")
        self.assertEqual(items[1].phone, "")
        self.assertIsNotNone(items[1].parse_error)

    def test_empty_input(self):
        self.assertEqual(self.parse("\n \r\n"), [])

    def test_default_cpca_strategy_uses_the_same_grouping(self):
        items = CpcaStrategy().parse_batch(f"测试甲 {PHONE_A}\n{ADDRESS_A}")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].address, "湖北省武汉市")
        self.assertIsNone(items[0].parse_error)


if __name__ == "__main__":
    unittest.main()
