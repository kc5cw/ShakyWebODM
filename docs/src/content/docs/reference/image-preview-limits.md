---
title: Image preview limits
---

Uploaded-image thumbnail requests accept `size` from 1 through 2048 pixels. The default remains 512 and small originals are not enlarged. Larger requests return HTTP 400.

The preview endpoint checks image dimensions before decoding and rejects sources above 100,000,000 pixels with HTTP 400. Original uploads remain available for downloads and processing. This limit applies to uploaded-image previews, not processing outputs or raster map tiles.

Recenter and zoom controls remain available. Annotations use finite normalized coordinates from -1 through 2 and radii from 0 through 100 percent. Invalid parameters return HTTP 400. Numeric normalization and annotation drawing run after the image has been reduced to the preview dimensions. JPEG decoder reduction is used where supported.

No database migration or new configuration is required. Deployment requires the normal application restart.
