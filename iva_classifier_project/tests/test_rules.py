import json
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main

class TestRules(unittest.TestCase):
    def test_service_matrix(self):
        self.assertEqual(main.classify_service(False, True)["iva_final"], "J1")
        self.assertEqual(main.classify_service(False, False)["iva_final"], "J3")
        self.assertEqual(main.classify_service(True, True)["iva_final"], "J2")
        self.assertEqual(main.classify_service(True, False)["iva_final"], "J4")

    def test_table_loaded(self):
        table = main.get_iva_table()
        self.assertGreaterEqual(len(table["mapeamentos"]), 20)
        self.assertIn("C$", [r["destino"] for r in table["mapeamentos"]])

    def test_ibs_mapping(self):
        table = main.get_iva_table()
        self.assertEqual(main.allowed_outputs("C0", True, table), ["C$"])
        self.assertEqual(main.allowed_outputs("C0", False, table), ["C0"])

if __name__ == "__main__":
    unittest.main()
