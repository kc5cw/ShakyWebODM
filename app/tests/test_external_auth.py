from django.contrib.auth.models import User, Group
from nodeodm.models import ProcessingNode
from rest_framework import status
from rest_framework.test import APIClient

from .classes import BootTestCase
from app.models import ExternalIdentity, Project
from app.auth.backends import ExternalBackend, get_user_from_external_auth_response
from app.auth.external_identity import external_provider_key
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from io import StringIO
from unittest.mock import patch

from .utils import start_simple_auth_server
from webodm import settings

class TestAuth(BootTestCase):
    def setUp(self):
        self.external_endpoint = settings.EXTERNAL_AUTH_ENDPOINT
        self.cluster_id = settings.CLUSTER_ID
        settings.EXTERNAL_AUTH_ENDPOINT = 'https://identity.example/auth'
        settings.CLUSTER_ID = None

    def tearDown(self):
        settings.EXTERNAL_AUTH_ENDPOINT = self.external_endpoint
        settings.CLUSTER_ID = self.cluster_id

    def test_ext_auth(self):
        client = APIClient()

        # Disable
        settings.EXTERNAL_AUTH_ENDPOINT = ''

        # Try to log-in
        ok = client.login(username='extuser1', password='test1234')
        self.assertFalse(ok)

        # Enable
        settings.EXTERNAL_AUTH_ENDPOINT = 'http://0.0.0.0:5555/auth'

        with start_simple_auth_server(["5555"]):
            ok = client.login(username='extuser1', password='invalid')
            self.assertFalse(ok)
            self.assertFalse(User.objects.filter(username="extuser1").exists())
            ok = client.login(username='extuser1', password='test1234')
            self.assertTrue(ok)
            user = User.objects.get(username="extuser1")
            self.assertEqual(ExternalIdentity.objects.get(user=user).external_user_id, '100')
            self.assertFalse(user.has_usable_password())
            self.assertEqual(user.profile.quota, 500)
            pnode = ProcessingNode.objects.get(token='test')
            self.assertEqual(pnode.hostname, 'localhost')
            self.assertEqual(pnode.port, 4444)
            self.assertTrue(user.has_perm('view_processingnode', pnode))
            self.assertFalse(user.has_perm('delete_processingnode', pnode))
            self.assertFalse(user.has_perm('change_processingnode', pnode))
            
            # Re-test login
            ok = client.login(username='extuser1', password='test1234')
            self.assertTrue(ok)

            # Check that the user has been added to the default group
            self.assertTrue(user.groups.filter(name='Default').exists())


    def test_numeric_collision_does_not_inherit_local_privileges(self):
        admin = User.objects.get(username='testsuperuser')
        before = (admin.username, admin.password, admin.profile.quota)
        user = get_user_from_external_auth_response({'user_id': admin.pk, 'username': 'external-new'})
        self.assertIsNotNone(user)
        self.assertNotEqual(user.pk, admin.pk)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.user_permissions.exists())
        admin.refresh_from_db()
        self.assertEqual((admin.username, admin.password, admin.profile.quota), before)
        self.assertTrue(admin.is_superuser)

    def test_username_collision_requires_explicit_link(self):
        local = User.objects.get(username='testuser')
        for external_id in (local.pk, local.pk + 1000):
            self.assertIsNone(get_user_from_external_auth_response({
                'user_id': external_id, 'username': local.username, 'maxQuota': 123}))
        self.assertFalse(ExternalIdentity.objects.exists())
        self.assertEqual(User.objects.get(pk=local.pk).profile.quota, -1)

    def test_explicit_link_preserves_projects_and_repeated_login(self):
        local = User.objects.get(username='testuser')
        projects = list(Project.objects.filter(owner=local).values_list('pk', flat=True))
        call_command('linkexternaluser', '--external-id', '00100', '--user', local.username,
                     '--dry-run', stdout=StringIO())
        self.assertFalse(ExternalIdentity.objects.exists())
        call_command('linkexternaluser', '--external-id', '00100', '--user', local.username,
                     stdout=StringIO())
        call_command('linkexternaluser', '--external-id', '100', '--user', local.username,
                     stdout=StringIO())
        response = {'user_id': 100, 'username': local.username, 'maxQuota': 500}
        for _ in range(2):
            self.assertEqual(get_user_from_external_auth_response(response).pk, local.pk)
        self.assertEqual(list(Project.objects.filter(owner=local).values_list('pk', flat=True)), projects)
        self.assertEqual(User.objects.get(pk=local.pk).profile.quota, 500)
        self.assertEqual(ExternalIdentity.objects.count(), 1)
        self.assertEqual(ExternalBackend().get_user(local.pk).pk, local.pk)

    def test_mapped_username_updates_cannot_take_over_local_account(self):
        user = get_user_from_external_auth_response({'user_id': 100, 'username': 'external-new'})
        renamed = get_user_from_external_auth_response({'user_id': 100, 'username': 'external-renamed'})
        self.assertEqual(renamed.pk, user.pk)
        self.assertIsNone(get_user_from_external_auth_response({'user_id': 100, 'username': 'testsuperuser'}))
        user.refresh_from_db()
        self.assertEqual(user.username, 'external-renamed')

    def test_provider_change_cannot_reuse_mapping_or_session(self):
        user = get_user_from_external_auth_response({'user_id': 100, 'username': 'external-new'})
        settings.EXTERNAL_AUTH_ENDPOINT = 'https://other-provider.example/auth'
        self.assertIsNone(ExternalBackend().get_user(user.pk))
        self.assertIsNone(get_user_from_external_auth_response({'user_id': 100, 'username': user.username}))
        other = get_user_from_external_auth_response({'user_id': 100, 'username': 'other-external'})
        self.assertNotEqual(other.pk, user.pk)
        self.assertEqual(ExternalIdentity.objects.count(), 2)

    def test_external_sessions_require_mapping_and_safe_account_status(self):
        self.assertIsNone(ExternalBackend().get_user(User.objects.get(username='testuser').pk))
        user = get_user_from_external_auth_response({'user_id': 100, 'username': 'external-new'})
        for field in ('is_staff', 'is_superuser', 'is_active'):
            User.objects.filter(pk=user.pk).update(**{field: field != 'is_active'})
            self.assertIsNone(ExternalBackend().get_user(user.pk))
            self.assertIsNone(get_user_from_external_auth_response({'user_id': 100, 'username': user.username}))
            User.objects.filter(pk=user.pk).update(**{field: field == 'is_active'})
        self.assertIsNotNone(ExternalBackend().get_user(user.pk))
        ExternalIdentity.objects.filter(user=user).delete()
        self.assertIsNone(ExternalBackend().get_user(user.pk))

    def test_link_command_refuses_privileged_and_conflicting_accounts(self):
        for username in ('testsuperuser', 'missing-user'):
            with self.assertRaises(CommandError):
                call_command('linkexternaluser', '--external-id', '100', '--user', username)
        local = User.objects.get(username='testuser')
        for field in ('is_staff', 'is_active'):
            User.objects.filter(pk=local.pk).update(**{field: field == 'is_staff'})
            with self.assertRaises(CommandError):
                call_command('linkexternaluser', '--external-id', '100', '--user', local.username)
            User.objects.filter(pk=local.pk).update(**{field: field == 'is_active'})
        call_command('linkexternaluser', '--external-id', '100', '--user', local.username, stdout=StringIO())
        for external_id, username in [('100', 'testuser2'), ('101', local.username)]:
            with self.assertRaises(CommandError):
                call_command('linkexternaluser', '--external-id', external_id, '--user', username)

    def test_invalid_external_ids_and_disabled_provider_fail_closed(self):
        for value in (True, False, 0, -1, 1.5, None, [], {}, '', '1.5', '-1', '9' * 256):
            self.assertIsNone(get_user_from_external_auth_response({'user_id': value, 'username': 'external-new'}))
        for response in (None, [], {}, {'user_id': 100}, {'user_id': 100, 'username': ''},
                         {'user_id': 100, 'username': 'x' * 151},
                         {'user_id': 100, 'username': 'external-new', 'error': 'denied'}):
            self.assertIsNone(get_user_from_external_auth_response(response))
        settings.CLUSTER_ID = 1
        for cluster_id in (2, None, 'invalid'):
            self.assertIsNone(get_user_from_external_auth_response({
                'user_id': 100, 'username': 'external-new', 'cluster_id': cluster_id}))
        settings.EXTERNAL_AUTH_ENDPOINT = ''
        self.assertIsNone(get_user_from_external_auth_response({'user_id': 100, 'username': 'external-new'}))
        self.assertIsNone(ExternalBackend().get_user(1))
        self.assertFalse(ExternalIdentity.objects.exists())

    def test_failed_mapping_insert_rolls_back_new_user(self):
        with patch('app.auth.backends.ExternalIdentity.objects.create', side_effect=IntegrityError):
            self.assertIsNone(get_user_from_external_auth_response({'user_id': 100, 'username': 'external-new'}))
        self.assertFalse(User.objects.filter(username='external-new').exists())

    def test_database_rejects_duplicate_identity_and_user_mappings(self):
        user = get_user_from_external_auth_response({'user_id': 100, 'username': 'external-new'})
        other = User.objects.get(username='testuser')
        for provider, external_id, local in [(external_provider_key(), '100', other),
                                              (external_provider_key(), '101', user)]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                ExternalIdentity.objects.create(provider=provider, external_user_id=external_id, user=local)

    def test_password_authentication_uses_identity_mapping(self):
        admin = User.objects.get(username='testsuperuser')
        with patch('app.auth.backends.requests.post') as post:
            post.return_value.json.return_value = {'user_id': admin.pk, 'username': 'external-new'}
            user = ExternalBackend().authenticate(None, username='external-new', password='external-secret')
        self.assertIsNotNone(user)
        self.assertNotEqual(user.pk, admin.pk)
        self.assertFalse(user.is_superuser)
        self.assertEqual(ExternalIdentity.objects.get(user=user).external_user_id, str(admin.pk))

    def test_token_login_uses_external_session_backend(self):
        from app.api.externalauth import ExternalTokenAuth
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().post('/api/external-token-auth/')
        request.COOKIES['external_access_token'] = 'test-provider-token'
        with patch('app.api.externalauth.requests.post') as post, \
                patch('app.api.externalauth.login') as login:
            post.return_value.json.return_value = {'user_id': 100, 'username': 'external-new'}
            response = ExternalTokenAuth.as_view()(request)
        self.assertEqual(response.data, {'redirect': '/'})
        login.assert_called_once()
        self.assertEqual(login.call_args[1]['backend'], 'app.auth.backends.ExternalBackend')
        self.assertEqual(ExternalIdentity.objects.get(user=login.call_args[0][1]).external_user_id, '100')

    def test_token_login_rejects_ambiguous_existing_account(self):
        from app.api.externalauth import ExternalTokenAuth
        from rest_framework.test import APIRequestFactory
        admin = User.objects.get(username='testsuperuser')
        request = APIRequestFactory().post('/api/external-token-auth/')
        request.COOKIES['external_access_token'] = 'test-provider-token'
        with patch('app.api.externalauth.requests.post') as post, \
                patch('app.api.externalauth.login') as login:
            post.return_value.json.return_value = {'user_id': admin.pk, 'username': admin.username}
            response = ExternalTokenAuth.as_view()(request)
        self.assertEqual(response.data, {'error': 'Invalid credentials'})
        login.assert_not_called()
