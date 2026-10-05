"""Serve untrusted task files as data, never as same-origin executable content."""
import os
import re
from urllib.parse import quote
from wsgiref.util import FileWrapper

from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from rest_framework import exceptions
from zipstream.ng import ZipStream


_INLINE_TYPES = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
    '.tif': 'image/tiff', '.tiff': 'image/tiff', '.avif': 'image/avif',
    '.ico': 'image/x-icon', '.json': 'application/json',
    '.geojson': 'application/geo+json', '.txt': 'text/plain',
    '.csv': 'text/plain', '.xyz': 'text/plain', '.obj': 'text/plain',
    '.mtl': 'text/plain',
}


def _set_asset_headers(response, content_type, disposition, filename, filesize):
    filename = os.path.basename(str(filename)) or 'download'
    if re.fullmatch(r'[A-Za-z0-9._-]+', filename):
        filename_header = 'filename={}'.format(filename)
    else:
        filename_header = "filename*=UTF-8''{}".format(quote(filename, safe=''))
    response['Content-Type'] = content_type
    response['Content-Disposition'] = '{}; {}'.format(disposition, filename_header)
    response['Content-Length'] = filesize
    response['X-Content-Type-Options'] = 'nosniff'
    # Defense in depth if a browser ever treats an asset as a document.
    # This response policy does not affect XHR/fetch or image decoding by viewers.
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"


def download_file_response(request, filePath, content_disposition, download_filename=None):
    filename = os.path.basename(filePath)
    download_filename = filename if download_filename is None else download_filename
    content_type = _INLINE_TYPES.get(os.path.splitext(filename)[1].lower())
    disposition = 'inline' if content_type and content_disposition == 'inline' else 'attachment'
    content_type = content_type or 'application/octet-stream'
    filesize = os.stat(filePath).st_size
    file = open(filePath, 'rb')
    stream = filesize > 1e8 or request.GET.get('_force_stream', False)
    if stream:
        response = FileResponse(file, content_type=content_type)
        response['_stream'] = 'yes'
    else:
        response = HttpResponse(FileWrapper(file), content_type=content_type)
    _set_asset_headers(response, content_type, disposition, download_filename, filesize)
    return response


def download_file_stream(request, stream, content_disposition, download_filename=None):
    if not isinstance(stream, ZipStream):
        raise exceptions.ValidationError('stream not a zipstream instance')
    # The bytes are a generated ZIP, regardless of a user-supplied filename or
    # inline query parameter. These parameters cannot select an executable MIME.
    response = StreamingHttpResponse(stream, content_type='application/zip')
    _set_asset_headers(response, 'application/zip', 'attachment',
                       download_filename or 'archive.zip', len(stream))
    response['_stream'] = 'yes'
    return response
