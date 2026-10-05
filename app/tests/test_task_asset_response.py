import io
import os
import tempfile
import zipfile
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from zipstream.ng import ZipStream

from app.task_asset_response import download_file_response, download_file_stream


class TestTaskAssetResponse(SimpleTestCase):
    def assert_protected(self, response, content_type, disposition):
        self.assertEqual(response['Content-Type'], content_type)
        self.assertTrue(response['Content-Disposition'].startswith(disposition + ';'))
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Content-Security-Policy'], "sandbox; default-src 'none'")

    def test_imported_active_content_is_download_only(self):
        payload = b'<script>parent.compromised = true</script>'
        source = io.BytesIO()
        with zipfile.ZipFile(source, 'w') as archive:
            for filename in ('page.html', 'image.svg', 'page.xhtml', 'page.xml', 'script.js',
                             'style.css', 'document.pdf', 'no-extension', 'page.HTML', 'image.SVG',
                             'page.png.html', 'unknown.bin'):
                archive.writestr(filename, payload)
        with tempfile.TemporaryDirectory() as directory:
            source.seek(0)
            with zipfile.ZipFile(source) as archive:
                archive.extractall(directory)
            for filename in os.listdir(directory):
                for force_stream in (False, True):
                    with self.subTest(filename=filename, stream=force_stream):
                        request = SimpleNamespace(GET={'inline': '1', '_force_stream': force_stream})
                        response = download_file_response(request, os.path.join(directory, filename), 'inline')
                        try:
                            self.assert_protected(response, 'application/octet-stream', 'attachment')
                            body = b''.join(response.streaming_content) if force_stream else response.content
                            self.assertEqual(body, payload)
                            self.assertEqual(int(response['Content-Length']), len(payload))
                        finally:
                            response.close()

    def test_raster_and_viewer_data_remain_readable(self):
        examples = {'image.png': 'image/png', 'image.JPG': 'image/jpeg', 'image.webp': 'image/webp',
                    'map.tif': 'image/tiff', 'ept.json': 'application/json',
                    'boundaries.geojson': 'application/geo+json', 'model.obj': 'text/plain',
                    'model.mtl': 'text/plain', 'points.xyz': 'text/plain', 'data.csv': 'text/plain'}
        with tempfile.TemporaryDirectory() as directory:
            for filename, content_type in examples.items():
                path = os.path.join(directory, filename)
                with open(path, 'wb') as output:
                    output.write(b'viewer fixture bytes')
                for force_stream in (False, True):
                    request = SimpleNamespace(GET={'_force_stream': force_stream})
                    response = download_file_response(request, path, 'inline')
                    try:
                        self.assert_protected(response, content_type, 'inline')
                        body = b''.join(response.streaming_content) if force_stream else response.content
                        self.assertEqual(body, b'viewer fixture bytes')
                    finally:
                        response.close()

    def test_custom_filename_cannot_change_actual_asset_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            for actual, renamed, content_type, disposition in (
                    ('page.html', 'safe.png', 'application/octet-stream', 'attachment'),
                    ('image.png', 'page.html', 'image/png', 'inline')):
                path = os.path.join(directory, actual)
                with open(path, 'wb') as output:
                    output.write(b'<script>alert(1)</script>')
                response = download_file_response(SimpleNamespace(GET={'inline': '1'}),
                                                  path, 'inline', download_filename=renamed)
                try:
                    self.assert_protected(response, content_type, disposition)
                finally:
                    response.close()

    def test_attachment_requests_for_safe_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'orthophoto.tif')
            with open(path, 'wb') as output:
                output.write(b'tiff fixture')
            response = download_file_response(SimpleNamespace(GET={}), path, 'attachment',
                                              download_filename='odm_orthophoto_NDVI.tif')
            try:
                self.assert_protected(response, 'image/tiff', 'attachment')
                self.assertEqual(response['Content-Disposition'],
                                 'attachment; filename=odm_orthophoto_NDVI.tif')
            finally:
                response.close()

    def test_generated_archive_type_and_disposition_ignore_filename_and_inline(self):
        for filename in ('archive.html', 'archive.svg', 'archive.js', 'archive.zip', None):
            stream = ZipStream(sized=True)
            stream.add(b'archive fixture', 'file.txt')
            response = download_file_stream(SimpleNamespace(GET={'inline': '1'}), stream, 'inline', filename)
            try:
                self.assert_protected(response, 'application/zip', 'attachment')
                body = b''.join(response.streaming_content)
                self.assertEqual(int(response['Content-Length']), len(body))
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    self.assertEqual(archive.read('file.txt'), b'archive fixture')
            finally:
                response.close()

    def test_filenames_are_header_encoded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'data.txt')
            with open(path, 'wb') as output:
                output.write(b'fixture')
            for filename in ('survey café.txt', 'name"; x=1.txt', 'file\r\nInjected: value.txt'):
                response = download_file_response(SimpleNamespace(GET={}), path, 'attachment', filename)
                try:
                    header = response['Content-Disposition']
                    self.assertTrue(header.startswith("attachment; filename*=UTF-8''"))
                    self.assertNotIn('\r', header)
                    self.assertNotIn('\n', header)
                    self.assertNotIn('"', header)
                finally:
                    response.close()

    def test_non_archive_stream_is_rejected(self):
        with self.assertRaises(ValidationError):
            download_file_stream(SimpleNamespace(GET={}), io.BytesIO(b'not a zip stream'), 'inline', 'page.html')
