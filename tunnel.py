import os
import re
import sys
import time
import asyncio
import logging
import subprocess
from typing import Optional

tunnel_process: Optional[subprocess.Popen] = None

def start_tunnel_sync(port: int = 8080) -> Optional[str]:
    """
    Cloudflare Tunnel (cloudflared.exe) ni orqa fonda ishga tushiradi
    va hosil bo'lgan rasmiy HTTPS manzilni qaytaradi.
    Hech qanday IP kiritish yoki ro'yxatdan o'tish talab qilinmaydi!
    """
    global tunnel_process

    import shutil
    exe_path = None
    if sys.platform == "win32":
        local_exe = os.path.join(os.path.dirname(__file__), "cloudflared.exe")
        if os.path.exists(local_exe):
            exe_path = local_exe
        else:
            exe_path = shutil.which("cloudflared")
    else:
        exe_path = shutil.which("cloudflared")
        if not exe_path:
            local_bin = os.path.join(os.path.dirname(__file__), "cloudflared")
            if os.path.exists(local_bin) and os.access(local_bin, os.X_OK):
                exe_path = local_bin

    if not exe_path:
        logging.info("Cloudflare tunnel (cloudflared) topilmadi. Avtomatik tunnel o'tkazib yuborildi.")
        return None

    try:
        cmd = [exe_path, "tunnel", "--url", f"http://localhost:{port}"]
        tunnel_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        url = None
        start_time = time.time()
        # 20 soniya ichida url chiqishini kutamiz
        while time.time() - start_time < 20:
            line = tunnel_process.stderr.readline()
            if not line:
                time.sleep(0.1)
                continue
            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if match:
                url = match.group(0)
                break

        if url:
            logging.info(f"🌐 Cloudflare Tunnel muvaffaqiyatli ulandi: {url}")
            return url
        else:
            logging.warning("Cloudflare Tunnel URL olinmadi (timeout).")
            return None
    except Exception as e:
        logging.error(f"Tunnel start error: {e}")
        return None


def stop_tunnel():
    """Tunnel jarayonini to'xtatadi."""
    global tunnel_process
    if tunnel_process:
        try:
            tunnel_process.terminate()
            tunnel_process.wait(timeout=2)
        except Exception:
            try:
                tunnel_process.kill()
            except Exception:
                pass
        tunnel_process = None
        logging.info("Cloudflare Tunnel to'xtatildi.")
