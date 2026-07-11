import os
from urllib.error import URLError
from urllib.request import urlopen

from app.plugins import Menu, MountPoint, PluginBase
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.translation import gettext as _


def planner_is_ready():
    health_url = os.environ.get(
        "FLIGHTPLANNER_HEALTH_URL", "http://flightplanner:3001/api/health"
    )
    try:
        with urlopen(health_url, timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


class Plugin(PluginBase):
    def main_menu(self):
        return [
            Menu(
                _("Flight Planner"),
                self.public_url(""),
                "fa fa-route fa-fw",
            )
        ]

    def app_mount_points(self):
        @login_required
        def index(request):
            return render(
                request,
                self.template_path("index.html"),
                {
                    "title": _("Flight Planner"),
                    "planner_ready": planner_is_ready(),
                    "planner_port": os.environ.get("FLIGHTPLANNER_PORT", "3001"),
                    "map_configured": bool(os.environ.get("MAPBOX_TOKEN", "").strip()),
                },
            )

        return [MountPoint("$", index)]
