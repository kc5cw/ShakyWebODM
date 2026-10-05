"""Download remote task archives without giving their URLs access to local services."""
import ipaddress
import os
import socket
import ssl
import tempfile
import zipfile
from urllib.parse import urljoin, urlsplit

import requests
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.exceptions import HTTPError, NewConnectionError
from urllib3.util import connection


class TaskImportError(ValueError):
    pass


class _PinnedConnectionMixin:
    def __init__(self, *args, pinned_ip, **kwargs):
        self.pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        # Keep self.host for Host/SNI/certificate verification, but never resolve
        # that hostname again when opening the socket.
        try:
            return connection.create_connection(
                (self.pinned_ip, self.port), self.timeout,
                source_address=self.source_address, socket_options=self.socket_options)
        except OSError as exc:
            raise NewConnectionError(self, 'Could not connect to archive host') from exc


class _PinnedHTTPConnection(_PinnedConnectionMixin, HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, HTTPSConnection):
    pass


class _PinnedHTTPPool(HTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))
_TRANSLATION_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    '64:ff9b::/96', '64:ff9b:1::/48', '2002::/16', '2001::/32'))


def _parse_url(url):
    if not isinstance(url, str) or not url or '\\' in url or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise TaskImportError('Invalid archive URL')
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError()
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError()
        hostname = parsed.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if not hostname or '%' in hostname or any(c.isspace() for c in hostname):
            raise ValueError()
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise TaskImportError('Invalid archive URL')
    return parsed, hostname, port


def _origin(parsed, hostname, port):
    return parsed.scheme, hostname, port


def _trusted_origins(values):
    origins = set()
    if isinstance(values, str):
        raise TaskImportError('Trusted archive origins must be a list')
    for value in values:
        parsed, hostname, port = _parse_url(value)
        if parsed.path not in ('', '/') or parsed.query:
            raise TaskImportError('Trusted archive origins cannot include paths or queries')
        origins.add(_origin(parsed, hostname, port))
    return origins


def _address_allowed(address, trusted):
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    if ip.version == 6 and (ip.is_site_local or any(ip in network for network in _TRANSLATION_NETWORKS)):
        return False
    return ip.is_global or (trusted and any(ip in network for network in _PRIVATE_NETWORKS
                                           if ip.version == network.version))


def resolve_archive_url(url, trusted_origins=()):
    parsed, hostname, port = _parse_url(url)
    trusted = _origin(parsed, hostname, port) in _trusted_origins(trusted_origins)
    try:
        addresses = sorted({result[4][0] for result in socket.getaddrinfo(
            hostname, port, type=socket.SOCK_STREAM)})
        # Reject mixed public/private DNS rather than picking a convenient answer.
        if not addresses or not all(_address_allowed(address, trusted) for address in addresses):
            raise TaskImportError('Archive URL resolves to a disallowed network address')
    except (OSError, ValueError) as exc:
        if isinstance(exc, TaskImportError):
            raise
        raise TaskImportError('Could not validate archive host') from exc
    return parsed, hostname, port, addresses[0]


def _open_archive_response(target):
    parsed, hostname, port, address = target
    pool_class = _PinnedHTTPSPool if parsed.scheme == 'https' else _PinnedHTTPPool
    options = {'pinned_ip': address, 'timeout': 10}
    if parsed.scheme == 'https':
        options.update(cert_reqs=ssl.CERT_REQUIRED, ca_certs=requests.certs.where())
    pool = pool_class(hostname, port, **options)
    host_header = '[{}]'.format(hostname) if ':' in hostname else hostname
    if port != (443 if parsed.scheme == 'https' else 80):
        host_header += ':{}'.format(port)
    path = parsed.path or '/'
    if parsed.query:
        path += '?' + parsed.query
    try:
        # Direct pools ignore environment proxies; redirects and retries must not
        # bypass validation or make a fresh hostname connection.
        response = pool.urlopen('GET', path, headers={'Host': host_header, 'Accept-Encoding': 'identity'},
                                redirect=False, retries=False, preload_content=False)
    except Exception:
        pool.close()
        raise
    return response, pool


def download_archive(url, destination, temp_dir, trusted_origins=(), progress=None):
    temporary_path = None
    try:
        for redirect_count in range(6):
            target = resolve_archive_url(url, trusted_origins)
            response, pool = _open_archive_response(target)
            try:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get('Location')
                    if not location or redirect_count == 5:
                        raise TaskImportError('Invalid or excessive archive redirects')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise TaskImportError('Archive server returned an unsuccessful response')
                length = response.headers.get('Content-Length')
                try:
                    total = int(length) if length is not None else None
                except ValueError:
                    total = None
                if total is not None and total <= 0:
                    total = None
                fd, temporary_path = tempfile.mkstemp(prefix='task-import-', suffix='.zip', dir=temp_dir)
                downloaded = 0
                with os.fdopen(fd, 'wb') as output:
                    for chunk in response.stream(4096, decode_content=False):
                        output.write(chunk)
                        downloaded += len(chunk)
                        if progress is not None:
                            progress(downloaded, total)
            finally:
                response.close()
                pool.close()
            # Parse the central directory before publishing any response body.
            try:
                with zipfile.ZipFile(temporary_path) as archive:
                    archive.infolist()
            except (zipfile.BadZipFile, OSError):
                raise TaskImportError('Invalid zip file')
            os.replace(temporary_path, destination)
            temporary_path = None
            return
    except (HTTPError, OSError) as exc:
        raise TaskImportError('Could not download archive') from exc
    finally:
        if temporary_path is not None:
            os.unlink(temporary_path)
