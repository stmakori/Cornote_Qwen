from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('notebooks', '0006_notebook_documents_and_pipeline'),
    ]

    operations = [
        migrations.AddField(
            model_name='notebook',
            name='target_question_count',
            field=models.PositiveSmallIntegerField(
                default=5,
                help_text='How many AI-generated study questions to create',
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10)],
            ),
        ),
    ]