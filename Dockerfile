# 段階5: Dockerで動かすための設計図
FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data

# 先にライブラリだけ入れる（コードを変えても、ここはキャッシュが効いて速い）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY rules.yaml .

# root ではないユーザーで動かす（安全のため）
RUN useradd --create-home appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "8000"]
