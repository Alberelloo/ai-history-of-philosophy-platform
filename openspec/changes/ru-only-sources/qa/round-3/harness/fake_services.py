"""Поддельные сервисы за шлюзом: возвращают эхо полученных заголовков.

Нужны, чтобы независимо от тестов репозитория увидеть, что именно шлюз передал
сервису: есть ли ``X-Philograph-Region``, с каким значением, и не просочился ли
клиентский регион или заголовок страны от CDN.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="fake-services")


@app.api_route("/{path:path}", methods=["GET", "POST"])
def echo(path: str, request: Request) -> JSONResponse:
    body = {
        "path": request.url.path,
        "query": request.url.query,
        "headers": [[k, v] for k, v in request.headers.items()],
    }
    response = JSONResponse(body)
    # Верхний сервис сам ставит Vary и публичный кэш: шлюз обязан переопределить
    # Cache-Control и дописать свой Vary, не потеряв прежнее значение.
    response.headers["Vary"] = "Accept-Encoding"
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
