"""Explicit PostgreSQL TLS handshake checks; no credentials or SQL."""
import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket
import ssl
import struct
from tempfile import TemporaryDirectory

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from dotenv import dotenv_values

from scripts.life_diary_backup_cloud_settings import POOLER_HOST, validate


def synthetic_ca(path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic TLS Test CA')])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                       critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def handshake(certificate, server_name):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(certificate))
    # Fixed network destination; only certificate name verification varies.
    with socket.create_connection((POOLER_HOST, 5432), timeout=5) as raw:
        raw.settimeout(5)
        raw.sendall(struct.pack('!II', 8, 80877103))
        if raw.recv(1) != b'S':
            raise ValueError('PostgreSQL TLS negotiation unavailable')
        with context.wrap_socket(raw, server_hostname=server_name) as secured:
            if not secured.getpeercert():
                raise ValueError('Verified certificate required')
    # No PostgreSQL startup, credentials or queries are sent.


def expect_rejected(action, allowed_codes):
    try:
        action()
    except ssl.SSLCertVerificationError as error:
        if error.verify_code not in allowed_codes:
            raise ValueError('Unexpected certificate rejection category') from None
        return
    raise ValueError('Expected certificate verification rejection')


def verify(certificate):
    handshake(certificate, POOLER_HOST)
    with TemporaryDirectory(prefix='jl-backup-tls-') as directory:
        unrelated = Path(directory) / 'synthetic-ca.crt'
        synthetic_ca(unrelated)
        # Untrusted issuer / self-signed chain categories.
        expect_rejected(
            lambda: handshake(unrelated, POOLER_HOST),
            {2, 18, 19, 20, 21})
    # OpenSSL hostname mismatch.
    expect_rejected(
        lambda: handshake(certificate, 'hostname-mismatch.invalid'),
        {62})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-settings', type=Path, required=True)
    parser.add_argument('--allow-cloud-tls-test', action='store_true')
    args = parser.parse_args()
    stage = 'INPUT'
    try:
        if not args.allow_cloud_tls_test:
            raise ValueError()
        if any(key.upper().startswith('PG') for key in os.environ):
            raise ValueError()
        stage = 'SETTINGS'
        config = validate(dotenv_values(args.backup_settings, interpolate=False))
        if not config.enabled:
            raise ValueError()
        stage = 'TLS_VERIFICATION'
        verify(config.certificate)
        print('PASS: TLS baseline; unrelated CA rejected; wrong hostname rejected')
        print('NO_DATABASE_AUTH: no password, startup message or SQL sent')
    except KeyboardInterrupt:
        raise SystemExit('STOPPED: TLS verification') from None
    except Exception:
        raise SystemExit(
            'BLOCKED: stage=' + stage + '; details suppressed') from None


if __name__ == '__main__':
    main()