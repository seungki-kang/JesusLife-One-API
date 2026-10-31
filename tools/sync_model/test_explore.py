import unittest
from unittest.mock import patch

from explore import Result, explore, main


class ExitStatusTests(unittest.TestCase):
    def test_exit_status_from_result(self):
        for errors, truncated, expected in (
            ((), False, 0),
            (("synthetic invariant error",), False, 1),
            ((), True, 1),
            (("synthetic invariant error",), True, 1),
        ):
            with self.subTest(errors=errors, truncated=truncated):
                result = Result(1, 0, 10, 60000, truncated, errors=errors)
                with patch("explore.explore", return_value=result) as mocked_explore:
                    with patch("builtins.print") as mocked_print:
                        self.assertEqual(main(), expected)
                mocked_explore.assert_called_once_with()
                mocked_print.assert_called_once_with(result)

    def test_depth_boundary_alone_is_not_truncation(self):
        result = explore(depth=0, state_limit=1)
        self.assertFalse(result.errors)
        self.assertFalse(result.truncated)
        self.assertEqual(result.states, 1)
        self.assertEqual(result.transitions, 0)

    def test_state_limit_can_truncate_before_depth_boundary(self):
        result = explore(depth=1, state_limit=1)
        self.assertFalse(result.errors)
        self.assertTrue(result.truncated)


if __name__ == "__main__":
    unittest.main()
