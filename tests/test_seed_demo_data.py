import tempfile
import unittest
from pathlib import Path

from coupon_bot.database import CouponRepository
from scripts.seed_demo_data import seed


class DemoCatalogueTests(unittest.TestCase):
    def test_seed_is_idempotent_and_covers_major_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = str(Path(directory) / "demo.db")

            self.assertEqual(seed(database_path), (22, 0))
            self.assertEqual(seed(database_path), (0, 22))

            repository = CouponRepository(database_path)
            try:
                self.assertEqual(len(repository.stores()), 22)
                self.assertEqual(repository.search("Amazon", page_size=10).total, 1)
                self.assertEqual(repository.search("Nykaa", page_size=10).total, 1)
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
