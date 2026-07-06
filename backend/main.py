import json
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from routers import forecast, metrics, symbols

app = FastAPI(title="EquiSight API", version="1.0")

# Simple in-memory response cache: the underlying data only changes when
# the forecasting pipeline is re-run (infrequent, manual), so there's no
# reason to hit Postgres on every request for endpoints that are read far
# more often than they change. This is what actually keeps latency low
# under load, not just async I/O.
_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, object]] = {}


async def cache_get_responses(request: Request, call_next):
    if request.method != "GET" or not request.url.path.startswith("/api/"):
        return await call_next(request)

    key = str(request.url)
    cached = _cache.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        response = JSONResponse(content=cached[1])
        response.headers["X-Cache"] = "HIT"
        return response

    response = await call_next(request)
    if response.status_code == 200:
        body = b"".join([chunk async for chunk in response.body_iterator])
        parsed = json.loads(body)
        _cache[key] = (now, parsed)
        response = JSONResponse(content=parsed, status_code=response.status_code)
        response.headers["X-Cache"] = "MISS"
    return response


# Middleware ordering matters here: add_middleware() wraps each new layer
# *around* the previous ones, so the last one added is outermost. We want,
# from outermost to innermost: GZip (compress the final bytes once) ->
# CORS (adds the header) -> our cache (reads/writes plain JSON, talks to
# the routes). Registering the cache middleware via add_middleware (not
# the @app.middleware("http") decorator, which is always forced outermost)
# is what makes this explicit ordering possible — otherwise the cache
# would read GZip-compressed bytes and crash trying to json.loads() them.
app.add_middleware(BaseHTTPMiddleware, dispatch=cache_get_responses)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # read-only public API, no auth/cookies to protect
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)

app.include_router(symbols.router)
app.include_router(forecast.router)
app.include_router(metrics.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
