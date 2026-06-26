from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('my_bite', '0005_menu_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='menuitem',
            name='voice_keywords',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
