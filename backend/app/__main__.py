"""python -m app  -> start the Fresh Vibe backend / camera bridge."""
import uvicorn

from .config import config

if __name__ == "__main__":
    ssl = {}
    if config.SSL_CERTFILE and config.SSL_KEYFILE:
        ssl = {"ssl_certfile": config.SSL_CERTFILE, "ssl_keyfile": config.SSL_KEYFILE}
    scheme = "https" if ssl else "http"
    shown = "localhost" if config.HOST in ("127.0.0.1", "0.0.0.0") else config.HOST
    print(f"\n  Fresh Vibe  ->  {scheme}://{shown}:{config.PORT}\n")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1", log_level="info", **ssl)
