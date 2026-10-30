"""Retirement proof using synthetic targets and no settings or external I/O."""
from contextlib import ExitStack, redirect_stderr
from io import StringIO
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/stage_mobile_client.py'


class RetiredStageTest(unittest.TestCase):
    def test_default_and_apply_refuse_before_any_file_access(self):
        code = compile(SCRIPT.read_text(encoding='utf-8'), str(SCRIPT), 'exec')
        for args in ([], ['--apply']):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / 'flutter/lib/main.dart'
                stage = root / '.mobile-stage/lib/main.dart'
                for path, content in ((target, b'authoritative synthetic source'),
                                      (stage, b'stale synthetic source')):
                    path.parent.mkdir(parents=True)
                    path.write_bytes(content)
                before = {str(p.relative_to(root)): p.read_bytes()
                          for p in root.rglob('*') if p.is_file()}
                namespace = {'__name__': '__main__', '__file__': str(SCRIPT),
                             'ROOT': target.parents[1], 'STAGE': stage.parents[1]}
                output = StringIO()
                with ExitStack() as guards, redirect_stderr(output):
                    guards.enter_context(patch.dict(os.environ, {}, clear=True))
                    guards.enter_context(patch('sys.argv', [str(SCRIPT), *args]))
                    # Includes reads of settings, target files and stale stage.
                    for name in ('builtins.open', 'io.open', 'os.scandir',
                                 'os.mkdir', 'os.remove', 'os.rename', 'os.replace'):
                        guards.enter_context(patch(name, side_effect=AssertionError(
                            'Retired staging must not access files')))
                    with self.assertRaises(SystemExit) as exit:
                        exec(code, namespace)
                self.assertEqual(exit.exception.code, 2)
                self.assertIn('actual Flutter repository', output.getvalue())
                self.assertIn('authoritative', output.getvalue())
                self.assertIn('stale and must not be applied', output.getvalue())
                after = {str(p.relative_to(root)): p.read_bytes()
                         for p in root.rglob('*') if p.is_file()}
                self.assertEqual(before, after)
