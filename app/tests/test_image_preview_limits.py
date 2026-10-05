import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from app.image_preview import render_preview


class ImagePreviewLimitsTest(unittest.TestCase):
    def test_oversized_header_rejected_before_decode(self):
        source = Mock(size=(10001, 10000))
        with self.assertRaises(ValueError):
            render_preview(source, 512)
        source.draft.assert_not_called()
        source.transform.assert_not_called()

    def test_output_limit_and_no_upscaling(self):
        source = Image.new('RGB', (3000, 1500))
        self.assertEqual(render_preview(source, 2048).size, (2048, 1024))
        for size in (0, -1, 2049, 9999999):
            with self.assertRaises(ValueError):
                render_preview(source, size)
        self.assertEqual(render_preview(Image.new('RGB', (48, 36)), 2048).size, (48, 36))

    def test_normalization_only_receives_bounded_pixels(self):
        source = Image.fromarray(np.arange(3000 * 1500, dtype=np.uint16).reshape(1500, 3000))
        original = np.asarray
        sizes = []
        def checked(image, **kwargs):
            sizes.append(image.size)
            return original(image, **kwargs)
        with patch('app.image_preview.np.asarray', side_effect=checked):
            result = render_preview(source, 512)
        self.assertEqual(sizes, [(512, 256)])
        self.assertEqual(result.mode, 'RGB')

    def test_recenter_zoom_and_annotations(self):
        source = Image.new('RGB', (100, 100), 'white')
        result = render_preview(source, 100, .3, .2, 2,
                                [dict(x=.3, y=.2, radius=3, color=(255, 0, 0))])
        self.assertEqual(result.getpixel((50, 47)), (255, 0, 0))
        self.assertEqual(result.getpixel((50, 50)), (255, 255, 255))
        self.assertEqual(result.getpixel((0, 0)), (0, 0, 0))
        for zoom in (.1, 1, 4, 10):
            self.assertEqual(render_preview(source, 64, zoom=zoom).size, (64, 64))

    def test_pixel_budget_boundary(self):
        source = Mock(size=(10000, 10000), mode='RGB')
        source.transform.return_value = Image.new('RGB', (1, 1))
        self.assertEqual(render_preview(source, 1).size, (1, 1))
        source.transform.assert_called_once()
