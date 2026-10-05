from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from app.api.tiler import Tiles


class TestTileLimits(SimpleTestCase):
    def test_oversized_or_invalid_scale_never_opens_raster(self):
        factory = APIRequestFactory()
        for scale in ('0', '3', '1000000', '9' * 10000, '-1', '1.5', 'abc', '',
                      '01', None, True, 1.5):
            with self.subTest(scale=str(scale)[:20]), \
                    patch('app.api.tiler.Tiles.get_and_check_task', return_value=Mock()), \
                    patch('app.api.tiler.get_raster_path') as raster_path, \
                    patch('app.api.tiler.COGReader') as reader:
                response = Tiles.as_view()(factory.get('/tile'), pk='1', z='10', x='1', y='1',
                                           tile_type='orthophoto', scale=scale, ext='png')
                self.assertEqual(response.status_code, 400)
                raster_path.assert_not_called()
                reader.assert_not_called()

    def test_standard_and_retina_tiles_use_bounded_dimensions(self):
        factory = APIRequestFactory()
        for base_size, scale, expected in ((256, '1', 256), (256, '2', 512),
                                           (512, '1', 512), (512, '2', 1024),
                                           (256, 1, 256), (256, 2, 512)):
            with self.subTest(base_size=base_size, scale=scale), \
                    patch('app.api.tiler.Tiles.get_and_check_task', return_value=Mock()), \
                    patch('app.api.tiler.get_raster_path', return_value='/fixture/raster.tif'), \
                    patch('app.api.tiler.os.path.isfile', return_value=True), \
                    patch('app.api.tiler.lookup_formula', return_value=(None, None)), \
                    patch('app.api.tiler.get_zoom_safe', return_value=(0, 20)), \
                    patch('app.api.tiler.has_alpha_band', return_value=False), \
                    patch('app.api.tiler.COGReader') as reader:
                source = reader.return_value.__enter__.return_value
                source.tile_exists.return_value = True
                source.dataset.colorinterp = []
                source.tile.return_value.post_process.return_value.render.return_value = b'tile fixture'
                response = Tiles.as_view()(factory.get('/tile', {'size': str(base_size)}),
                                           pk='1', z='10', x='1', y='1',
                                           tile_type='orthophoto', scale=scale, ext='png')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b'tile fixture')
                self.assertEqual(response['Content-Type'], 'image/png')
                self.assertEqual(source.tile.call_args[1]['tilesize'], expected)
                self.assertLessEqual(expected, 1024)
                self.assertEqual(source.tile.call_args[0], (1, 1, 9 if base_size == 512 else 10))

    def test_invalid_base_size_still_rejected_before_raster_access(self):
        factory = APIRequestFactory()
        for size in ('1024', '2048', '-1', 'abc'):
            with self.subTest(size=size), \
                    patch('app.api.tiler.Tiles.get_and_check_task', return_value=Mock()), \
                    patch('app.api.tiler.COGReader') as reader:
                response = Tiles.as_view()(factory.get('/tile', {'size': size}), pk='1', z='10',
                                           x='1', y='1', tile_type='orthophoto', scale='2', ext='png')
                self.assertEqual(response.status_code, 400)
                reader.assert_not_called()
