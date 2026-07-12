import unittest

from receipt_ocr.categorizer import categorize_items
from receipt_ocr.parser import parse_receipt


CONFIG = {
    "parser": {
        "tax_included_keywords": ["合計", "税込"],
        "ignore_line_keywords": ["TEL", "レジ", "お預り", "釣銭"],
    },
    "categories": {
        "食費": ["牛乳", "パン"],
        "日用品": ["洗剤"],
    },
}


class ParserTest(unittest.TestCase):
    def test_parse_basic_receipt(self):
        text = """スーパー青山
2026/06/14
牛乳 198
洗剤 398
合計 596
お預り 1000
"""
        receipt = parse_receipt(text, CONFIG)
        receipt.items = categorize_items(receipt.items, CONFIG)

        self.assertEqual(receipt.shop_name, "スーパー青山")
        self.assertEqual(receipt.purchased_at, "2026-06-14")
        self.assertEqual(receipt.total_amount, 596)
        self.assertEqual(len(receipt.items), 2)
        self.assertEqual(receipt.items[0].category, "食費")
        self.assertEqual(receipt.items[1].category, "日用品")

    def test_parse_abc_mart_ocr_text(self):
        text = """ABC-MART
領収証
ABCブランチ神戸学園都市
TEL 078-797-6830
2026年05月03日（日）11時04分
#3616
04 ABC SELECT
$0050
内
04,389
6890190001
サイズ
1点
小計
合計
（含む消費税等
（10%対象
9
4,389
009999
¥4,389
¥4，
389
¥399）
¥399）
¥4,389 消費税
クレジットカード
伝票No.
15876
カード番号
¥4,389
XXXXXXXXXXXX6628
登録番号 12011001033515
01195088012605033616
0880880136163
"""
        receipt = parse_receipt(text, CONFIG)

        self.assertEqual(receipt.shop_name, "ABC-MART")
        self.assertEqual(receipt.purchased_at, "2026-05-03")
        self.assertEqual(receipt.total_amount, 4389)
        self.assertIn(("ABC SELECT", 4389), [(item.name, item.amount) for item in receipt.items])

    def test_parse_abc_mart_card_sales_slip(self):
        text = """ABC-MART
タッチ決済売上票
お客様控
ABCブランチ神戸学園都市
TEL 078-797-6830
2026年05月03日(日) 11時04分
#3616
加盟店名 I-ビージーマートブランチコウベガクエ
ご利用日 26/05/03 11:04:44
カード会社 MUFGカード
カード番号 CL 422002XXXXXX6628
端末番号 55084-510-33363
伝票番号 15876
承認番号 224574
取引区分 売上
支払区分 一括
日計金額 ¥4,389
AID A0000000031010
ATC 0000000075
カードシーケンス番号 00
アプリケーションラベル VISACREDIT
店:1950 レジ:8801 001972
株式会社 エービーシー・マート
登録番号 T2011001033515
0880880136163
"""
        receipt = parse_receipt(text, CONFIG)

        self.assertEqual(receipt.shop_name, "ABC-MART")
        self.assertEqual(receipt.purchased_at, "2026-05-03")
        self.assertEqual(receipt.total_amount, 4389)
        self.assertNotEqual(receipt.total_amount, 224574)


if __name__ == "__main__":
    unittest.main()
