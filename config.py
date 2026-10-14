import os

API_ID = int(os.getenv("API_ID", "33465516"))
API_HASH = os.getenv("API_HASH", "8c3c061c71bdbb70da28dc677b13e678")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8901205517:AAG3zYMQbTtOQGasDsz2LfJ5xeMZdn_TIrU")

ADMIN_ID_1 = int(os.getenv("ADMIN_ID_1", "1784313012"))
ADMIN_ID_2 = int(os.getenv("ADMIN_ID_2", "1052561222"))
ADMIN_IDS = [ADMIN_ID_1, ADMIN_ID_2]
ADMIN_ID = ADMIN_ID_1  


WEEKLY_STARS = int(os.getenv("WEEKLY_STARS", "50"))     
MONTHLY_STARS = int(os.getenv("MONTHLY_STARS", "200"))  


DEFAULT_SPEED = 2.0
ALLOWED_SPEEDS = [1.5, 2.0, 3.0, 5.0]
HARD_TAG_LIMIT = 400                                    


WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8080")))
def _get_webapp_url() -> str:
    url = (os.getenv("WEBAPP_URL", "").strip() or 
           os.getenv("RENDER_EXTERNAL_URL", "").strip() or 
           (f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME').strip()}" if os.getenv("RENDER_EXTERNAL_HOSTNAME") else ""))
    if url:
        url = url.rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"
    return url

WEBAPP_URL = _get_webapp_url()
