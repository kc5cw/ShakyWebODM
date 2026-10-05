from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from app.auth.external_identity import external_provider_key, normalize_external_user_id
from app.models import ExternalIdentity


class Command(BaseCommand):
    help = 'Explicitly link a verified external identity to an existing local user.'

    def add_arguments(self, parser):
        parser.add_argument('--external-id', required=True)
        parser.add_argument('--user', required=True, help='Existing local username')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            provider = external_provider_key()
            external_id = normalize_external_user_id(options['external_id'])
            with transaction.atomic():
                user = User.objects.select_for_update().get(username=options['user'])
                if not user.is_active or user.is_staff or user.is_superuser:
                    raise CommandError('Only active, non-staff, non-superuser accounts may be linked')
                identity = ExternalIdentity.objects.filter(
                    provider=provider, external_user_id=external_id).first()
                if identity is not None and identity.user_id != user.pk:
                    raise CommandError('External identity is already linked to another account')
                if ExternalIdentity.objects.filter(user=user).exclude(
                        provider=provider, external_user_id=external_id).exists():
                    raise CommandError('Local account is already linked to another external identity')
                if options['dry_run']:
                    self.stdout.write('Would link external ID {} to local user {} (ID {})'.format(
                        external_id, user.username, user.pk))
                    return
                ExternalIdentity.objects.get_or_create(
                    provider=provider, external_user_id=external_id, defaults={'user': user})
        except User.DoesNotExist:
            raise CommandError('Local user does not exist')
        except (ValueError, IntegrityError) as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS('Linked external ID {} to local user {} (ID {})'.format(
            external_id, user.username, user.pk)))
