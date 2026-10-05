from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from navigation import focus_lvce_source_control


class NavigationTest(unittest.TestCase):
    def test_git_ready_before_sidebar_does_not_send_early_shortcut(self):
        page = Mock()
        mounted = False

        def evaluate(_):
            return mounted

        def mount_sidebar(_):
            nonlocal mounted
            mounted = True

        def key(*_):
            self.assertTrue(mounted, 'Shortcut must wait for the mounted sidebar')

        page.evaluate.side_effect = evaluate
        page.key.side_effect = key
        process = Mock()
        process.poll.return_value = None
        with patch('navigation.time.sleep', side_effect=mount_sidebar), patch('navigation.time.monotonic', return_value=1):
            focus_lvce_source_control(page, process, 60)
        page.call.assert_called_once_with('Page.bringToFront')
        page.key.assert_called_once_with('g', 'KeyG', 10)

    def test_missing_sidebar_fails_without_sending_input(self):
        page = Mock()
        page.evaluate.return_value = False
        process = Mock()
        process.poll.return_value = None
        with patch('navigation.time.monotonic', return_value=60), self.assertRaises(TimeoutError):
            focus_lvce_source_control(page, process, 60)
        page.key.assert_not_called()

    def test_editor_exit_during_startup_fails_without_sending_input(self):
        page = Mock()
        page.evaluate.return_value = False
        process = Mock()
        process.poll.return_value = 1
        with self.assertRaises(RuntimeError):
            focus_lvce_source_control(page, process, 60)
        page.key.assert_not_called()
