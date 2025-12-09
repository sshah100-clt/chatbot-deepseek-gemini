INSTALLED_APPS += ["chat"]
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
ALLOWED_HOSTS = ["*"]        
CSRF_TRUSTED_ORIGINS = ["http://localhost:8000"]
