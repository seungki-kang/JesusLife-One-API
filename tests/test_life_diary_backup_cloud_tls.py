"""Offline TLS verification tests; no network access."""
from pathlib import Path
import ssl
import struct
import unittest
from unittest.mock import MagicMock, patch

from scripts import life_diary_backup_cloud_tls as cli


def certificate_error(code):
    error = ssl.SSLCertVerificationError(1, 'synthetic certificate failure')
    error.verify_code = code
    return error


class CloudTlsTests(unittest.TestCase):
    def test_expected_certificate_rejection(self):
        for code in (2, 18, 19, 20, 21, 62):
            with self.subTest(code=code):
                action = MagicMock(side_effect=certificate_error(code))
                cli.expect_rejected(action, {code})
                action.assert_called_once_with()

    def test_unexpected_certificate_category_fails(self):
        action = MagicMock(side_effect=certificate_error(10))
        with self.assertRaises(ValueError):
            cli.expect_rejected(action, {62})

    def test_network_error_is_not_a_successful_rejection(self):
        action = MagicMock(side_effect=TimeoutError('synthetic timeout'))
        with self.assertRaises(TimeoutError):
            cli.expect_rejected(action, {62})

    def test_unexpected_connection_success_fails(self):
        with self.assertRaises(ValueError):
            cli.expect_rejected(lambda: None, {62})

    def test_handshake_uses_fixed_target_and_only_ssl_request(self):
        with patch.object(cli.socket, 'create_connection') as connect, \
             patch.object(cli.ssl, 'SSLContext') as context_factory:
            raw = connect.return_value.__enter__.return_value
            raw.recv.return_value = b'S'
            context = context_factory.return_value
            secured = context.wrap_socket.return_value.__enter__.return_value
            secured.getpeercert.return_value = {'subject': 'synthetic'}

            cli.handshake(Path('synthetic-ca.crt'), 'hostname-mismatch.invalid')

            connect.assert_called_once_with((cli.POOLER_HOST, 5432), timeout=5)
            context_factory.assert_called_once_with(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations.assert_called_once_with(
                cafile='synthetic-ca.crt')
            context.wrap_socket.assert_called_once_with(
                raw, server_hostname='hostname-mismatch.invalid')
            raw.sendall.assert_called_once_with(
                struct.pack('!II', 8, 80877103))
            secured.send.assert_not_called()
            secured.sendall.assert_not_called()

    def test_server_without_tls_is_rejected(self):
        with patch.object(cli.socket, 'create_connection') as connect, \
             patch.object(cli.ssl, 'SSLContext') as context_factory:
            raw = connect.return_value.__enter__.return_value
            raw.recv.return_value = b'N'
            with self.assertRaises(ValueError):
                cli.handshake(Path('synthetic-ca.crt'), cli.POOLER_HOST)
            context_factory.return_value.wrap_socket.assert_not_called()


if __name__ == '__main__':
    unittest.main()