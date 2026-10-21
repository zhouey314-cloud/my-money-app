from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ledger import (DuplicateExpense, InvalidExpense, UnsafeLedger, backup_ledger,
                    load_ledger, migrate_copy, save_expense)

SYNTHETIC = {'item': 'SYNTHETIC tea', 'amount': 12.3, 'category': '餐饮', 'currency': 'CNY'}
NOW = datetime(2026, 1, 2, 3, 4)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic.csv'

    def test_round_trip_does_not_mutate_input(self):
        original = SYNTHETIC.copy()
        save_expense(original, self.path, recorded_at=NOW)
        self.assertEqual(original, SYNTHETIC)
        self.assertEqual(load_ledger(self.path)[0]['amount'], '12.30')
        self.assertEqual(load_ledger(self.path)[0]['date'], '2026-01-02 03:04')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_values_never_create_ledger(self):
        for amount in [0, -1, True, float('inf'), float('nan'), 1.001, '12']:
            with self.subTest(amount_type=type(amount).__name__):
                with self.assertRaises(InvalidExpense):
                    save_expense({**SYNTHETIC, 'amount': amount}, self.path)
                self.assertFalse(self.path.exists())

    def test_duplicate_refused_and_explicit_override(self):
        save_expense(SYNTHETIC, self.path, recorded_at=NOW)
        before = self.path.read_bytes()
        with self.assertRaises(DuplicateExpense):
            save_expense(SYNTHETIC, self.path, recorded_at=NOW)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(len(save_expense(SYNTHETIC, self.path, recorded_at=NOW, allow_duplicate=True)), 2)

    def test_backup_matches_original_bytes(self):
        save_expense(SYNTHETIC, self.path, recorded_at=NOW)
        before = self.path.read_bytes()
        save_expense({**SYNTHETIC, 'item': 'SYNTHETIC lunch'}, self.path, recorded_at=NOW)
        backups = list(self.path.parent.glob('synthetic.csv.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

    def test_replace_failure_preserves_ledger_and_backup(self):
        save_expense(SYNTHETIC, self.path, recorded_at=NOW)
        before = self.path.read_bytes()
        with patch('ledger.os.replace', side_effect=OSError('synthetic filesystem failure')):
            with self.assertRaises(OSError):
                save_expense({**SYNTHETIC, 'item': 'SYNTHETIC second'}, self.path, recorded_at=NOW)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))
        self.assertEqual(next(self.path.parent.glob('*.backup-*')).read_bytes(), before)

    def test_malformed_existing_ledger_is_not_overwritten(self):
        cases = [b'', b'wrong,header\n1,2\n', b'item,amount,category,currency,date\nsynthetic,NaN,other,CNY,invalid\n', b'\xff\xfe']
        for raw in cases:
            self.path.write_bytes(raw)
            with self.assertRaises(UnsafeLedger):
                save_expense(SYNTHETIC, self.path)
            self.assertEqual(self.path.read_bytes(), raw)
            self.assertFalse(list(self.path.parent.glob('*.backup-*')))

    def test_invalid_calendar_date_is_refused(self):
        self.path.write_text('item,amount,category,currency,date\nSYNTHETIC,1.00,其他,CNY,2026-02-30 03:04\n')
        with self.assertRaises(UnsafeLedger):
            load_ledger(self.path)

    def test_spreadsheet_formula_in_existing_file_is_refused(self):
        self.path.write_text('item,amount,category,currency,date\n=FORMULA(),1.00,其他,CNY,2026-01-02 03:04\n')
        with self.assertRaises(UnsafeLedger):
            load_ledger(self.path)

    def test_symlink_target_is_untouched(self):
        target = self.path.parent / 'private-synthetic-target'
        target.write_text('SYNTHETIC sentinel')
        self.path.symlink_to(target)
        with self.assertRaises(UnsafeLedger):
            save_expense(SYNTHETIC, self.path)
        self.assertEqual(target.read_text(), 'SYNTHETIC sentinel')

    def test_concurrent_writes_do_not_lose_rows(self):
        def write(index):
            save_expense({**SYNTHETIC, 'item': 'SYNTHETIC ' + str(index)}, self.path, recorded_at=NOW)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(12)))
        self.assertEqual(len(load_ledger(self.path)), 12)

    def test_migration_is_a_new_copy_and_preserves_source(self):
        save_expense(SYNTHETIC, self.path, recorded_at=NOW)
        before = self.path.read_bytes()
        destination = self.path.parent / 'new.csv'
        self.assertEqual(migrate_copy(self.path, destination), 1)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(load_ledger(destination), load_ledger(self.path))
        with self.assertRaises(FileExistsError):
            migrate_copy(self.path, destination)

    def test_explicit_backup_can_preserve_a_damaged_file(self):
        self.path.write_bytes(b'SYNTHETIC invalid CSV')
        backup = backup_ledger(self.path)
        self.assertEqual(backup.read_bytes(), self.path.read_bytes())

    def test_cli_refusal_never_outputs_values(self):
        marker = 'SYNTHETIC_PRIVATE_SENTINEL'
        self.path.write_text(marker)
        result = subprocess.run([sys.executable, 'ledger.py', 'check', '--path', str(self.path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertEqual(self.path.read_text(), marker)


if __name__ == '__main__':
    unittest.main()
