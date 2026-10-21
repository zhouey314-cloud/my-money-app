"""Synthetic parser cases only. This does not measure model extraction quality."""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest


def parser():
    baseline = os.environ.get('LEDGER_PARSER_BASELINE_SOURCE')
    if not baseline:
        from ledger import parse_model_response
        return parse_model_response
    # Execute only the original helper with a fake provider, never Streamlit UI,
    # real credentials, files, top-level imports or a network call.
    tree = ast.parse(Path(baseline).read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_ai_response')
    def legacy(content):
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        fake = SimpleNamespace(OpenAI=lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))))
        namespace = {'json': json, 'openai': fake, 'st': SimpleNamespace(error=lambda _: None)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<original-helper>', 'exec'), namespace)
        return namespace['get_ai_response']('synthetic', '', '', 'mock')
    return legacy


class ModelSchemaTests(unittest.TestCase):
    def test_reject_invalid_provider_output(self):
        base = {'item': 'SYNTHETIC tea', 'amount': 12.30, 'category': '餐饮', 'currency': 'CNY'}
        cases = [[], True, {**base, 'amount': -1}, {**base, 'amount': True},
                 {**base, 'amount': '12.30'}, {**base, 'amount': float('nan')},
                 {**base, 'amount': 1.001}, {**base, 'date': '2026-01-01'},
                 {**base, 'item': '=SYNTHETIC()'}, {**base, 'category': 'unknown'}]
        parse = parser()
        for case in cases:
            with self.subTest(kind=type(case).__name__, case_index=cases.index(case)):
                with self.assertRaises(ValueError):
                    parse(json.dumps(case, ensure_ascii=False))

    def test_duplicate_json_fields_are_not_silently_replaced(self):
        with self.assertRaises(ValueError):
            parser()('{"item":"synthetic","amount":1,"amount":2,"category":"其他","currency":"CNY"}')

    def test_valid_model_object_and_exact_json_fence(self):
        text = '{"item":"SYNTHETIC tea","amount":12.30,"category":"餐饮","currency":"CNY"}'
        for content in [text, '```json\n' + text + '\n```']:
            self.assertEqual(parser()(content)['item'], 'SYNTHETIC tea')


if __name__ == '__main__':
    unittest.main()
