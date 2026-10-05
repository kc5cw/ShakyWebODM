from django.conf import settings
from django.db import models


class ExternalIdentity(models.Model):
    # Hash the configured endpoint to namespace identities without storing its secrets.
    provider = models.CharField(max_length=64)
    external_user_id = models.CharField(max_length=255)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='external_identity')

    class Meta:
        unique_together = (('provider', 'external_user_id'),)
