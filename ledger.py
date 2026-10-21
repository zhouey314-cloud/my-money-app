"""Offline validation and conservative CSV storage. No model or network imports."""
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

FIELDS = ('item', 'amount', 'category', 'currency', 'date')
CATEGORIES = {'餐饮', '交通', '购物', '居住', '娱乐', '医疗', '其他'}


class InvalidExpense(ValueError):
    """Invalid input. Messages intentionally contain no input values."""


class DuplicateExpense(InvalidExpense):
    pass


class UnsafeLedger(InvalidExpense):
    pass


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise InvalidExpense('Missing or invalid text field.')
    value = value.strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or value[0] in '=+-@':
        raise InvalidExpense('Control characters and spreadsheet formulas are not allowed.')
    return value


def _amount(value, *, csv_value=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal) + ((str,) if csv_value else ())):
        raise InvalidExpense('Amount must be a JSON number.')
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('.01')):
            raise InvalidExpense('Amount must be positive, finite and have at most two decimal places.')
        return format(amount, '.2f')
    except (InvalidOperation, ValueError, OverflowError):
        raise InvalidExpense('Invalid amount.') from None


def validate_expense(value, *, recorded_at=None, csv_value=False):
    expected = set(FIELDS if csv_value else FIELDS[:-1])
    if not isinstance(value, dict) or set(value) != expected:
        raise InvalidExpense('Expense fields do not match the expected schema.')
    item = _text(value['item'], 200)
    category = _text(value['category'], 20)
    currency = _text(value['currency'], 3)
    if category not in CATEGORIES or re.fullmatch(r'[A-Z]{3}', currency) is None:
        raise InvalidExpense('Invalid category or currency format.')
    if csv_value:
        date = value['date']
        if not isinstance(date, str):
            raise InvalidExpense('Invalid date.')
        try:
            parsed = datetime.strptime(date, '%Y-%m-%d %H:%M')
            if parsed.strftime('%Y-%m-%d %H:%M') != date:
                raise ValueError
        except ValueError:
            raise InvalidExpense('Invalid date; expected YYYY-MM-DD HH:MM.') from None
    else:
        date = (recorded_at or datetime.now()).strftime('%Y-%m-%d %H:%M')
    return dict(zip(FIELDS, (item, _amount(value['amount'], csv_value=csv_value), category, currency, date)))


def parse_model_response(content):
    if not isinstance(content, str) or len(content) > 100_000:
        raise InvalidExpense('Model response is missing or too large.')
    content = content.strip()
    if content.startswith('```json\n') and content.endswith('\n```'):
        content = content[8:-4].strip()
    def reject_constant(_):
        raise InvalidExpense('Non-finite JSON numbers are not allowed.')
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise InvalidExpense('Duplicate JSON fields are not allowed.')
            obj[key] = value
        return obj
    try:
        data = json.loads(content, parse_float=Decimal, parse_int=Decimal,
                          parse_constant=reject_constant, object_pairs_hook=unique_object)
    except (ValueError, TypeError, RecursionError):
        raise InvalidExpense('Model response is not a valid expense object.') from None
    validate_expense(data)
    return data


def _path(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise UnsafeLedger('Ledger must be a regular file, never a symlink.')
    if not path.parent.is_dir():
        raise UnsafeLedger('Ledger directory does not exist.')
    return path


@contextmanager
def _lock(path):
    # macOS/Linux advisory locking. Unsupported platforms fail instead of racing.
    try:
        import fcntl
    except ImportError:
        raise UnsafeLedger('This storage adapter requires macOS or Linux file locking.') from None
    fd = os.open(path.with_name('.' + path.name + '.lock'),
                 os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnsafeLedger('Lock must be a regular file.')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _read(path):
    if not path.exists():
        return []
    try:
        with path.open(encoding='utf-8-sig', newline='') as source:
            reader = csv.DictReader(source, strict=True)
            if reader.fieldnames is None or len(reader.fieldnames) != len(FIELDS) or set(reader.fieldnames) != set(FIELDS):
                raise UnsafeLedger('Ledger header is invalid; original file was preserved.')
            return [validate_expense(row, csv_value=True) for row in reader]
    except (UnicodeError, csv.Error, InvalidExpense):
        raise UnsafeLedger('Ledger is malformed; original file was preserved. Check or restore a backup.') from None


def load_ledger(path='my_expenses.csv'):
    path = _path(path)
    with _lock(path):
        _path(path)
        return _read(path)


def _backup(path):
    backup = path.with_name(path.name + '.backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex)
    raw = path.read_bytes()
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    return backup


def backup_ledger(path='my_expenses.csv'):
    path = _path(path)
    with _lock(path):
        _path(path)
        if not path.exists():
            raise UnsafeLedger('Ledger does not exist.')
        return _backup(path)  # Byte-for-byte backup also works for a malformed ledger.


def _csv_bytes(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode('utf-8')


def save_expense(value, path='my_expenses.csv', *, recorded_at=None, allow_duplicate=False):
    row = validate_expense(value, recorded_at=recorded_at)
    path = _path(path)
    with _lock(path):
        _path(path)
        rows = _read(path)
        if not allow_duplicate and row in rows:
            raise DuplicateExpense('An identical expense already exists for this minute; nothing was written.')
        rows.append(row)
        # Validate everything before creating backups or replacing the original.
        payload = _csv_bytes(rows)
        if path.exists():
            _backup(path)
        fd, temp_name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as target:
                target.write(payload)
                target.flush()
                os.fsync(target.fileno())
            _path(path)
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)
    return rows


def migrate_copy(source, destination):
    """Validate and copy to a NEW file, preserving source bytes and old schema."""
    rows = load_ledger(source)
    destination = _path(destination)
    payload = _csv_bytes(rows)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as target:
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())
    return len(rows)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Offline ledger check/backup/non-destructive copy. Never prints expense values.')
    parser.add_argument('command', choices=['check', 'backup', 'migrate-copy'])
    parser.add_argument('--path', default='my_expenses.csv')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        if args.command == 'check':
            print(json.dumps({'status': 'VALID', 'rows': len(load_ledger(args.path))}))
        elif args.command == 'backup':
            backup_ledger(args.path)
            print(json.dumps({'status': 'BACKUP_CREATED', 'values_output': False}))
        else:
            if not args.output:
                parser.error('--output is required for migrate-copy')
            print(json.dumps({'status': 'COPY_CREATED', 'rows': migrate_copy(args.path, args.output)}))
        return 0
    except (InvalidExpense, OSError):
        print(json.dumps({'status': 'REFUSED', 'values_output': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
