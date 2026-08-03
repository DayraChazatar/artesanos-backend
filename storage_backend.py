import os
from supabase import create_client

def upload_image(file, bucket: str, filename: str) -> str:
    """Sube una imagen a Supabase Storage y retorna la URL pública."""
    client = create_client(
        os.getenv('SUPABASE_URL'),
        os.getenv('SUPABASE_SERVICE_KEY')
    )
    data = file.read()
    client.storage.from_(bucket).upload(
        path=filename,
        file=data,
        file_options={"content-type": file.content_type}
    )
    return client.storage.from_(bucket).get_public_url(filename)