import datetime as dt
import sqlite3
import unittest

from coupon_bot.database import CouponRepository


class CouponRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = CouponRepository(":memory:")

    def tearDown(self) -> None:
        self.repository.close()

    def test_add_search_and_mark_used(self) -> None:
        coupon_id = self.repository.add_coupon(
            store="Example Store",
            code="save20",
            title="Twenty percent off running shoes",
            discount="20% off",
            category="Fashion",
            description="Valid on selected products.",
        )

        page = self.repository.search("running shoes", page_size=10)
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].code, "SAVE20")
        self.assertEqual(page.items[0].view_count, 0)

        viewed = self.repository.record_view(coupon_id)
        self.assertIsNotNone(viewed)
        self.assertEqual(viewed.view_count, 1)
        self.assertTrue(self.repository.mark_used(coupon_id))
        self.assertEqual(self.repository.get_active(coupon_id).used_count, 1)

    def test_expired_coupon_is_not_listed(self) -> None:
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        self.repository.add_coupon(
            store="Old Store",
            code="OLD10",
            title="Expired offer",
            expires_at=yesterday,
        )

        page = self.repository.list_active(page_size=10)
        self.assertEqual(page.total, 0)

    def test_duplicate_store_and_code_is_rejected_case_insensitively(self) -> None:
        arguments = {
            "store": "Same Store",
            "code": "Deal10",
            "title": "First offer",
        }
        self.repository.add_coupon(**arguments)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.add_coupon(
                store="same store",
                code="DEAL10",
                title="Duplicate offer",
            )

    def test_deactivate_removes_coupon_from_active_results(self) -> None:
        coupon_id = self.repository.add_coupon(
            store="Store",
            code="HIDE1",
            title="Hidden offer",
        )
        self.assertTrue(self.repository.deactivate(coupon_id))
        self.assertIsNone(self.repository.get_active(coupon_id))
        self.assertFalse(self.repository.deactivate(coupon_id))


if __name__ == "__main__":
    unittest.main()
