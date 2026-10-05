import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from app.task_import_url import (TaskImportError, resolve_archive_url, download_archive,
                                 _PinnedHTTPConnection, _PinnedHTTPSConnection,
                                 _open_archive_response)


def dns_answers(*addresses):
    return [(0, 0, 0, '', (address, 80)) for address in addresses]


def zip_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('images.json', '[]')
    return buffer.getvalue()


def response(status=200, body=None, headers=None):
    result = Mock(status=status, headers=headers or {})
    result.stream.return_value = [zip_bytes() if body is None else body]
    return result


class TestTaskImportURL(unittest.TestCase):
    def test_nonpublic_and_transition_addresses_are_blocked(self):
        for address in ('127.0.0.1', '10.0.0.83', '172.16.0.1', '192.168.1.1',
                        '169.254.169.254', '0.0.0.0', '224.0.0.1', '100.64.0.1',
                        '240.0.0.1', '::1', '::', 'fe80::1', 'fc00::1', 'ff02::1',
                        'fec0::1', '::ffff:127.0.0.1', '::ffff:10.0.0.83',
                        '64:ff9b::a00:53', '2002:a00:5300::1', '2001::1'):
            with self.subTest(address=address), patch('app.task_import_url.socket.getaddrinfo',
                                                     return_value=dns_answers(address)):
                with self.assertRaises(TaskImportError):
                    resolve_archive_url('https://archive.example/all.zip')

    def test_public_addresses_and_normalized_hostname(self):
        for address in ('93.184.216.34', '2606:4700:4700::1111', '::ffff:93.184.216.34'):
            with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers(address)):
                target = resolve_archive_url('https://ARCHIVE.EXAMPLE.:8443/all.zip?key=value')
            self.assertEqual(target[1:], ('archive.example', 8443, address))

    def test_mixed_dns_answers_are_rejected(self):
        with patch('app.task_import_url.socket.getaddrinfo',
                   return_value=dns_answers('93.184.216.34', '10.0.0.83')):
            with self.assertRaises(TaskImportError):
                resolve_archive_url('https://archive.example/all.zip')

    def test_legacy_numeric_ip_forms_are_checked_after_resolution(self):
        for url in ('http://2130706433/all.zip', 'http://0x7f000001/all.zip',
                    'http://127.1/all.zip'):
            with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('127.0.0.1')):
                with self.assertRaises(TaskImportError):
                    resolve_archive_url(url)

    def test_invalid_urls_and_dns_failures(self):
        for url in (None, [], '', 'file:///etc/passwd', 'ftp://archive.example/all.zip',
                    'http://user:password@archive.example/all.zip', 'http://archive.example:0/',
                    'http://archive.example:65536/', 'http://[invalid]/',
                    'http://archive.example/#fragment', 'http://archive.example/\nheader',
                    'http://archive.example\\@localhost/', 'http://local%host/'):
            with self.subTest(url=url), self.assertRaises(TaskImportError):
                resolve_archive_url(url)
        for answers in ([],):
            with patch('app.task_import_url.socket.getaddrinfo', return_value=answers):
                with self.assertRaises(TaskImportError):
                    resolve_archive_url('https://archive.example/')
        with patch('app.task_import_url.socket.getaddrinfo', side_effect=OSError):
            with self.assertRaises(TaskImportError):
                resolve_archive_url('https://archive.example/')

    def test_trusted_origins_are_exact_and_only_allow_private_lan(self):
        trusted = ['https://nas.example:8443']
        with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('10.0.0.83')):
            self.assertEqual(resolve_archive_url('https://nas.example:8443/all.zip', trusted)[3], '10.0.0.83')
            for url in ('http://nas.example:8443/', 'https://nas.example/',
                        'https://other.example:8443/', 'https://sub.nas.example:8443/'):
                with self.assertRaises(TaskImportError):
                    resolve_archive_url(url, trusted)
        for address in ('127.0.0.1', '169.254.169.254', '240.0.0.1', 'fe80::1'):
            with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers(address)):
                with self.assertRaises(TaskImportError):
                    resolve_archive_url('https://nas.example:8443/', trusted)
        for invalid in (['https://nas.example/path'], ['https://nas.example/?key=secret'],
                        'https://nas.example'):
            with self.assertRaises(TaskImportError):
                resolve_archive_url('https://nas.example/', invalid)

    def test_connections_pin_ip_without_changing_tls_hostname(self):
        with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('93.184.216.34')) as dns:
            target = resolve_archive_url('https://archive.example/all.zip')
        for connection_class in (_PinnedHTTPConnection, _PinnedHTTPSConnection):
            connection = connection_class(target[1], target[2], pinned_ip=target[3], timeout=10)
            with patch('app.task_import_url.connection.create_connection') as connect:
                connection._new_conn()
            self.assertEqual(connect.call_args[0][0], ('93.184.216.34', 443))
            self.assertEqual(connection.host, 'archive.example')
        dns.assert_called_once()

    def test_https_checks_certificates_and_ignores_proxy_environment(self):
        import ssl
        with patch.dict(os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:9999'}), \
                patch('app.task_import_url._PinnedHTTPSPool') as pool_class:
            target = (Mock(scheme='https', path='/all.zip', query='key=value'),
                                       'archive.example', 8443, '93.184.216.34')
            result, pool = _open_archive_response(target)
        self.assertEqual(pool_class.call_args[0], ('archive.example', 8443))
        self.assertEqual(pool_class.call_args[1]['pinned_ip'], '93.184.216.34')
        self.assertEqual(pool_class.call_args[1]['cert_reqs'], ssl.CERT_REQUIRED)
        self.assertTrue(pool_class.call_args[1]['ca_certs'])
        call = pool.urlopen.call_args
        self.assertEqual(call[0], ('GET', '/all.zip?key=value'))
        self.assertEqual(call[1]['headers']['Host'], 'archive.example:8443')
        self.assertFalse(call[1]['redirect'])
        self.assertFalse(call[1]['retries'])
        self.assertFalse(call[1]['preload_content'])

    def test_public_zip_is_published_only_after_validation(self):
        body = zip_bytes()
        result, pool = response(body=body, headers={'Content-Length': str(len(body))}), Mock()
        with tempfile.TemporaryDirectory() as directory:
            temp_dir = os.path.join(directory, 'temporary')
            destination = os.path.join(directory, 'all.zip')
            def progress(downloaded, total):
                self.assertFalse(os.path.exists(destination))
                self.assertEqual((downloaded, total), (len(body), len(body)))
            with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('93.184.216.34')), \
                    patch('app.task_import_url._open_archive_response', return_value=(result, pool)):
                download_archive('https://archive.example/all.zip', destination, temp_dir, progress=progress)
            with open(destination, 'rb') as downloaded:
                self.assertEqual(downloaded.read(), body)
            self.assertEqual(os.listdir(temp_dir), [])
        result.close.assert_called_once()
        pool.close.assert_called_once()

    def test_failed_downloads_do_not_leave_readable_response_bodies(self):
        for result in (response(body=b'internal-service-secret'), response(status=404),
                       response(status=302), response(body=b'PK\x03\x04truncated')):
            with tempfile.TemporaryDirectory() as directory:
                destination = os.path.join(directory, 'all.zip')
                pool = Mock()
                with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('93.184.216.34')), \
                        patch('app.task_import_url._open_archive_response', return_value=(result, pool)):
                    with self.assertRaises(TaskImportError):
                        download_archive('https://archive.example/all.zip', destination, directory)
                self.assertEqual(os.listdir(directory), [])
                result.close.assert_called_once()
                pool.close.assert_called_once()

    def test_cancellation_cleans_temporary_download(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('93.184.216.34')), \
                    patch('app.task_import_url._open_archive_response', return_value=(response(), Mock())):
                with self.assertRaises(RuntimeError):
                    download_archive('https://archive.example/all.zip', os.path.join(directory, 'all.zip'),
                                     directory, progress=Mock(side_effect=RuntimeError('canceled')))
            self.assertEqual(os.listdir(directory), [])

    def test_redirect_to_internal_destination_is_blocked_before_connection(self):
        redirected, pool = response(status=302, headers={'Location': 'http://169.254.169.254/latest/'}), Mock()
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.task_import_url.socket.getaddrinfo',
                       side_effect=[dns_answers('93.184.216.34'), dns_answers('169.254.169.254')]), \
                    patch('app.task_import_url._open_archive_response', return_value=(redirected, pool)) as open_response:
                with self.assertRaises(TaskImportError):
                    download_archive('https://archive.example/all.zip', os.path.join(directory, 'all.zip'), directory)
                open_response.assert_called_once()
            self.assertEqual(os.listdir(directory), [])
        redirected.close.assert_called_once()
        pool.close.assert_called_once()

    def test_relative_public_redirect_is_followed_and_dns_rechecked(self):
        redirected = response(status=302, headers={'Location': '/archive.zip'})
        success = response()
        pools = [Mock(), Mock()]
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('93.184.216.34')) as dns, \
                    patch('app.task_import_url._open_archive_response', side_effect=[(redirected, pools[0]), (success, pools[1])]) as open_response:
                download_archive('https://archive.example/start', os.path.join(directory, 'all.zip'), directory)
                self.assertEqual(dns.call_count, 2)
                self.assertEqual(open_response.call_args_list[1][0][0][0].path, '/archive.zip')
            self.assertEqual(os.listdir(directory), ['all.zip'])
        for pool in pools:
            pool.close.assert_called_once()

    def test_redirects_cannot_bypass_rebinding_checks(self):
        redirected = response(status=302, headers={'Location': '/archive.zip'})
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.task_import_url.socket.getaddrinfo',
                       side_effect=[dns_answers('93.184.216.34'), dns_answers('10.0.0.83')]), \
                    patch('app.task_import_url._open_archive_response', return_value=(redirected, Mock())) as open_response:
                with self.assertRaises(TaskImportError):
                    download_archive('https://archive.example/start', os.path.join(directory, 'all.zip'), directory)
                open_response.assert_called_once()
            self.assertEqual(os.listdir(directory), [])

    def test_excessive_redirects_are_bounded(self):
        redirected = response(status=302, headers={'Location': '/again'})
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.task_import_url.socket.getaddrinfo', return_value=dns_answers('93.184.216.34')), \
                    patch('app.task_import_url._open_archive_response', return_value=(redirected, Mock())) as open_response:
                with self.assertRaises(TaskImportError):
                    download_archive('https://archive.example/start', os.path.join(directory, 'all.zip'), directory)
                self.assertEqual(open_response.call_count, 6)
            self.assertEqual(os.listdir(directory), [])

    @unittest.skipUnless(__import__('shutil').which('openssl'), 'OpenSSL is needed for the TLS fixture')
    def test_real_tls_preserves_sni_host_and_certificate_verification(self):
        import socket
        import ssl
        import subprocess
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from app.task_import_url import connection
        real_dns = socket.getaddrinfo
        real_connect = connection.create_connection
        seen_hosts, seen_sni, resolved_hosts = [], [], []
        body = zip_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen_hosts.append(self.headers['Host'])
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with tempfile.TemporaryDirectory() as directory:
            key = os.path.join(directory, 'key.pem')
            cert = os.path.join(directory, 'cert.pem')
            config = os.path.join(directory, 'cert.cnf')
            with open(config, 'w') as output:
                output.write('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n'
                             '[dn]\nCN=archive.example\n[ext]\nsubjectAltName=DNS:archive.example\n')
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', key, '-out', cert, '-days', '1', '-config', config],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            context.set_servername_callback(lambda sock, hostname, ctx: seen_sni.append(hostname))
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def dns(host, *args, **kwargs):
                    resolved_hosts.append(host)
                    if host in ('archive.example', 'wrong.example'):
                        return dns_answers('93.184.216.34')
                    return real_dns(host, *args, **kwargs)

                def route_pinned_socket(address, *args, **kwargs):
                    self.assertEqual(address, ('93.184.216.34', server.server_port))
                    # Test transport only: route the validated public IP to our
                    # fixture without changing the production URL or TLS hostname.
                    return real_connect(('127.0.0.1', server.server_port), *args, **kwargs)

                destination = os.path.join(directory, 'all.zip')
                with patch('app.task_import_url.socket.getaddrinfo', side_effect=dns), \
                        patch('app.task_import_url.connection.create_connection', side_effect=route_pinned_socket), \
                        patch('app.task_import_url.requests.certs.where', return_value=cert), \
                        patch.dict(os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:1'}):
                    download_archive('https://archive.example:{}/all.zip'.format(server.server_port),
                                     destination, directory)
                    with open(destination, 'rb') as downloaded:
                        self.assertEqual(downloaded.read(), body)
                    rejected_path = os.path.join(directory, 'rejected.zip')
                    with self.assertRaises(TaskImportError):
                        download_archive('https://wrong.example:{}/all.zip'.format(server.server_port),
                                         rejected_path, directory)
                    self.assertFalse(os.path.exists(rejected_path))
                self.assertEqual(seen_hosts, ['archive.example:{}'.format(server.server_port)])
                self.assertEqual(seen_sni, ['archive.example', 'wrong.example'])
                self.assertEqual(resolved_hosts.count('archive.example'), 1)
                self.assertEqual(resolved_hosts.count('wrong.example'), 1)
                self.assertFalse(any(name.startswith('task-import-') for name in os.listdir(directory)))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
