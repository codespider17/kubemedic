FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN uv pip install --system --no-cache . \
    && groupadd --gid 10001 kubemedic \
    && useradd --uid 10001 --gid 10001 --no-create-home kubemedic \
    && install -d -o 10001 -g 10001 /data

USER 10001:10001

EXPOSE 5001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5001"]
