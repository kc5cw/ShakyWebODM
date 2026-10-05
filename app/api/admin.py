from django.contrib.auth.models import User, Group
from app.models import Profile
from rest_framework import serializers, viewsets, generics, status, exceptions
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAdminUser
from rest_framework.response import Response
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.hashers import make_password
from app import models

class IsActiveSuperuser(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'password', 'first_name', 'last_name', 'email',
                  'is_active', 'is_staff', 'is_superuser', 'groups',
                  'user_permissions', 'last_login', 'date_joined')
        read_only_fields = ('id', 'last_login', 'date_joined')
        extra_kwargs = {'password': {'write_only': True, 'required': False,
                                     'allow_blank': False}}

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data.get('password'))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'password' in validated_data:
            validated_data['password'] = make_password(validated_data['password'])
        return super().update(instance, validated_data)


class AdminUserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsActiveSuperuser]

    def get_queryset(self):
        queryset = User.objects.all()
        email = self.request.query_params.get('email', None)
        if email is not None:
            queryset = queryset.filter(email=email)
        return queryset

class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Group
        fields = ('id', 'name', 'permissions')

class AdminGroupViewSet(viewsets.ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsActiveSuperuser]

    def get_queryset(self):
        queryset = Group.objects.all()
        name = self.request.query_params.get('name', None)
        if name is not None:
            queryset = queryset.filter(name=name)
        return queryset


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Profile
        exclude = ('id', ) 

        read_only_fields = ('user', )

class AdminProfileViewSet(viewsets.ModelViewSet):
    pagination_class = None
    serializer_class = ProfileSerializer
    permission_classes = [IsAdminUser]
    lookup_field = 'user'
    
    def get_queryset(self):
        return Profile.objects.all()

    
    @action(detail=True, methods=['post'])
    def update_quota_deadline(self, request, user=None):
        try:
            hours = float(request.data.get('hours', ''))
            if hours < 0:
                raise ValueError("hours must be >= 0")
        except ValueError as e:
            raise exceptions.ValidationError(str(e))

        try:
            p = Profile.objects.get(user=user)
        except ObjectDoesNotExist:
            raise exceptions.NotFound()
        
        return Response({'deadline': p.set_quota_deadline(hours)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def used_quota(self, request, user=None):
        try:
            p = Profile.objects.get(user=user)
        except ObjectDoesNotExist:
            raise exceptions.NotFound()

        return Response({'used': p.used_quota(), 'total': p.quota}, status=status.HTTP_200_OK)
