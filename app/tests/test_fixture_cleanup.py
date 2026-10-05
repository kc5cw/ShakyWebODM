import subprocess
import unittest
from unittest.mock import Mock, patch

from app.tests.utils import start_processing_node, start_simple_auth_server


class TestFixtureCleanup(unittest.TestCase):
    def test_servers_stop_when_a_test_fails(self):
        for fixture in (start_processing_node, start_simple_auth_server):
            process = Mock()
            with self.subTest(fixture=fixture.__name__), \
                    patch('app.tests.utils.subprocess.Popen', return_value=process), \
                    patch('app.tests.utils.time.sleep'):
                with self.assertRaises(AssertionError):
                    with fixture():
                        raise AssertionError('failing test')
                process.terminate.assert_called_once_with()
                process.wait.assert_called_once_with(timeout=10)
                process.kill.assert_not_called()

    def test_unresponsive_servers_are_killed_and_reaped(self):
        for fixture in (start_processing_node, start_simple_auth_server):
            process = Mock()
            process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 10), 0]
            with self.subTest(fixture=fixture.__name__), \
                    patch('app.tests.utils.subprocess.Popen', return_value=process), \
                    patch('app.tests.utils.time.sleep'):
                with fixture():
                    pass
                process.kill.assert_called_once_with()
                self.assertEqual(process.wait.call_count, 2)
