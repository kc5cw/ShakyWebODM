from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('app', '0047_task_wkt'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExternalIdentity',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False,
                                        verbose_name='ID')),
                ('provider', models.CharField(max_length=64)),
                ('external_user_id', models.CharField(max_length=255)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='external_identity',
                                              to=settings.AUTH_USER_MODEL)),
            ],
            options={'unique_together': {('provider', 'external_user_id')}},
        ),
    ]
