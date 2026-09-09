# Migración editada a mano: el orden importa. Antes de borrar
# Categoria.artesano, copiamos esa relación al nuevo Usuario.categoria para
# no perder qué artesano tenía asignada cuál categoría (ej. "Arte en Telas").

import django.db.models.deletion
from django.db import migrations, models


def copiar_categoria_a_usuario(apps, schema_editor):
    Categoria = apps.get_model('usuarios', 'Categoria')
    for categoria in Categoria.objects.exclude(artesano__isnull=True):
        Usuario = apps.get_model('usuarios', 'Usuario')
        Usuario.objects.filter(pk=categoria.artesano_id).update(categoria_id=categoria.pk)


def revertir_categoria_a_usuario(apps, schema_editor):
    Usuario = apps.get_model('usuarios', 'Usuario')
    Categoria = apps.get_model('usuarios', 'Categoria')
    for usuario in Usuario.objects.exclude(categoria__isnull=True):
        Categoria.objects.filter(pk=usuario.categoria_id).update(artesano_id=usuario.pk)


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0017_alter_producto_visible'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario',
            name='categoria',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='artesanos', to='usuarios.categoria'),
        ),
        migrations.RunPython(copiar_categoria_a_usuario, revertir_categoria_a_usuario),
        migrations.RemoveField(
            model_name='categoria',
            name='artesano',
        ),
    ]
