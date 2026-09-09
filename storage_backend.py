import io
import os
from supabase import create_client
from PIL import Image

# Lado más largo permitido para una foto de producto/perfil. Con esto de
# sobra para verse nítido en pantalla; nunca hace falta más.
MAX_DIMENSION = 1600
CALIDAD_JPEG = 82


def _procesar_imagen(file, max_dimension=MAX_DIMENSION, calidad=CALIDAD_JPEG):
    """
    Redimensiona (si hace falta) y recomprime la imagen antes de subirla, sin
    cambiar su formato original (una foto PNG sigue siendo PNG, con su
    transparencia intacta; una JPEG sigue siendo JPEG). Esto es lo que evita
    que el catálogo tenga que descargar fotos de varios MB tal como salieron
    de la cámara del celular.

    Si algo sale mal al procesarla (formato raro, archivo corrupto, etc.), se
    sube el archivo original tal cual, para no bloquear al usuario.
    """
    try:
        file.seek(0)
        imagen = Image.open(file)
        formato = (imagen.format or 'JPEG').upper()
        if formato not in ('JPEG', 'PNG', 'WEBP'):
            formato = 'JPEG'

        ancho, alto = imagen.size
        if max(ancho, alto) > max_dimension:
            ratio = max_dimension / max(ancho, alto)
            nuevo_tamano = (round(ancho * ratio), round(alto * ratio))
            imagen = imagen.resize(nuevo_tamano, Image.LANCZOS)

        if formato == 'JPEG' and imagen.mode not in ('RGB', 'L'):
            # JPEG no admite transparencia; si la imagen la tenía, se pierde
            # aquí (es lo esperado al guardar como JPEG).
            imagen = imagen.convert('RGB')

        buffer = io.BytesIO()
        guardar_kwargs = {'optimize': True}
        if formato == 'JPEG':
            guardar_kwargs['quality'] = calidad
        imagen.save(buffer, format=formato, **guardar_kwargs)
        buffer.seek(0)
        return buffer.getvalue(), f'image/{formato.lower()}'
    except Exception:
        file.seek(0)
        return file.read(), getattr(file, 'content_type', 'application/octet-stream')


def upload_image(file, bucket: str, filename: str) -> str:
    """Sube una imagen a Supabase Storage (ya redimensionada/comprimida) y
    retorna la URL pública."""
    client = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_KEY')
    )
    data, content_type = _procesar_imagen(file)
    client.storage.from_(bucket).upload(
        path=filename,
        file=data,
        file_options={"content-type": content_type}
    )
    return client.storage.from_(bucket).get_public_url(filename)