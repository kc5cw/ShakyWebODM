import os
import io
import math

from .tasks import TaskNestedView
from rest_framework import exceptions
from PIL import Image
from django.http import HttpResponse
from .tasks import download_file_response
from .common import hex2rgb
from app.image_preview import MAX_THUMBNAIL_SIZE, render_preview

class Thumbnail(TaskNestedView):
    def get(self, request, pk=None, project_pk=None, image_filename=""):
        """
        Generate a thumbnail on the fly for a particular task's image
        """
        task = self.get_and_check_task(request, pk)
        image_path = task.get_image_path(image_filename)
        if not os.path.isfile(image_path):
            raise exceptions.NotFound()

        try:
            thumb_size = int(self.request.query_params.get('size', 512))
            if not 1 <= thumb_size <= MAX_THUMBNAIL_SIZE:
                raise ValueError()

            quality = int(self.request.query_params.get('quality', 75))
            if quality < 0 or quality > 100:
                raise ValueError()
                
            center_x = float(self.request.query_params.get('center_x', '0.5'))
            center_y = float(self.request.query_params.get('center_y', '0.5'))
            if not (-0.5 <= center_x <= 1.5 and -0.5 <= center_y <= 1.5):
                raise ValueError()

            draw_points = self.request.query_params.getlist('draw_point')
            point_colors = self.request.query_params.getlist('point_color')
            point_radiuses = self.request.query_params.getlist('point_radius')
            
            points = []
            i = 0
            for p in draw_points:
                coords = list(map(float, p.split(",")))
                if len(coords) != 2 or not all(math.isfinite(c) and -1 <= c <= 2 for c in coords):
                    raise ValueError()

                points.append({
                    'x': coords[0],
                    'y': coords[1],
                    'color': hex2rgb(point_colors[i]) if i < len(point_colors) else (255, 255, 255),
                    'radius': float(point_radiuses[i]) if i < len(point_radiuses) else 1.0,
                })

                if not 0 <= points[-1]['radius'] <= 100:
                    raise ValueError()
                i += 1
            
            zoom = float(self.request.query_params.get('zoom', '1'))
            if not 0.1 <= zoom <= 10:
                raise ValueError()

        except ValueError:
            raise exceptions.ValidationError("Invalid query parameters")

        try:
            with Image.open(image_path) as source:
                img = render_preview(source, thumb_size, center_x, center_y, zoom, points)
        except (ValueError, Image.DecompressionBombError):
            raise exceptions.ValidationError("Image exceeds preview limits")

        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, progressive=True)

        res = HttpResponse(content_type="image/jpeg")
        res['Content-Disposition'] = 'inline'
        res.write(output.getvalue())
        output.close()

        return res

class ImageDownload(TaskNestedView):
    def get(self, request, pk=None, project_pk=None, image_filename=""):
        """
        Download a task's image
        """
        task = self.get_and_check_task(request, pk)
        image_path = task.get_image_path(image_filename)
        if not os.path.isfile(image_path):
            raise exceptions.NotFound()

        return download_file_response(request, image_path, 'attachment')