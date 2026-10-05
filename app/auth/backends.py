import requests
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from app.models import ExternalIdentity
from app.auth.external_identity import external_provider_key, normalize_external_user_id
from nodeodm.models import ProcessingNode
from webodm import settings
from guardian.shortcuts import assign_perm
import logging

logger = logging.getLogger('app.logger')

def cluster_mismatch(res):
    if settings.CLUSTER_ID is None:
        return False

    if 'cluster_id' in res:
        # Check cluster ID field
        try:
            return int(res['cluster_id']) != settings.CLUSTER_ID
        except (TypeError, ValueError):
            return True
    return False

def resolve_external_identity(res):
    try:
        provider = external_provider_key()
        external_id = normalize_external_user_id(res['user_id'])
        username = res['username']
        if not isinstance(username, str) or not username or len(username) > User._meta.get_field('username').max_length:
            return None

        with transaction.atomic():
            identity = ExternalIdentity.objects.select_for_update().filter(
                provider=provider, external_user_id=external_id).first()
            if identity is None:
                # Never infer ownership from a matching local username or primary key.
                # Existing accounts must be linked explicitly by an administrator.
                if User.objects.filter(username=username).exists():
                    return None
                user = User(username=username, is_staff=False, is_superuser=False)
                user.set_unusable_password()
                user.save()
                ExternalIdentity.objects.create(provider=provider,
                                                external_user_id=external_id, user=user)
            else:
                user = User.objects.select_for_update().get(pk=identity.user_id)
                if not user.is_active or user.is_staff or user.is_superuser:
                    return None
                if user.username != username:
                    if User.objects.exclude(pk=user.pk).filter(username=username).exists():
                        return None
                    user.username = username
                    user.save(update_fields=['username'])
            return user
    except (KeyError, TypeError, ValueError, IntegrityError):
        # Concurrent first logins or username changes fail closed; no orphan user
        # is committed because user creation and mapping share a transaction.
        return None


def get_user_from_external_auth_response(res):
    if not isinstance(res, dict) or 'message' in res or 'error' in res:
        return None

    if 'user_id' in res and 'username' in res:
        if cluster_mismatch(res):
            return None
        user = resolve_external_identity(res)
        if user is None:
            return None

        maxQuota = -1
        if 'maxQuota' in res:
            maxQuota = res['maxQuota']
        if 'node' in res and 'limits' in res['node'] and 'maxQuota' in res['node']['limits']:
            maxQuota = res['node']['limits']['maxQuota']

        # Update quotas
        if user.profile.quota != maxQuota:
            user.profile.quota = maxQuota
            user.save()

        # Setup/update processing node
        if 'node' in res and 'hostname' in res['node'] and 'port' in res['node']:
            hostname = res['node']['hostname']
            port = res['node']['port']
            token = res['node'].get('token', '')

            # Only add/update if a token is provided, since we use 
            # tokens as unique identifiers for hostname/port updates
            if token != "":
                try:
                    node = ProcessingNode.objects.get(token=token)
                    if node.hostname != hostname or node.port != port:
                        node.hostname = hostname
                        node.port = port
                        node.save()
                    
                except ProcessingNode.DoesNotExist:
                    node = ProcessingNode(hostname=hostname, port=port, token=token)
                    node.save()
                
                if not user.has_perm('view_processingnode', node):
                    assign_perm('view_processingnode', user, node)

        return user
    else:
        return None

class ExternalBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None):
        if settings.EXTERNAL_AUTH_ENDPOINT == "":
            return None
        
        try:
            r = requests.post(settings.EXTERNAL_AUTH_ENDPOINT, {
                'username': username,
                'password': password
            }, headers={'Accept': 'application/json'})
            res = r.json()

            return get_user_from_external_auth_response(res)
        except:
            return None
    
    def get_user(self, user_id):
        if settings.EXTERNAL_AUTH_ENDPOINT == "":
            return None

        try:
            identity = ExternalIdentity.objects.select_related('user').get(
                provider=external_provider_key(), user_id=user_id)
            user = identity.user
            if user.is_active and not user.is_staff and not user.is_superuser:
                return user
        except (ExternalIdentity.DoesNotExist, TypeError, ValueError):
            pass
        return None
