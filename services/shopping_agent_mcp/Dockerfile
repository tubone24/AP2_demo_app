FROM python:3.14-slim

WORKDIR /app

# システムパッケージ更新
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 依存関係をコピー
COPY pyproject.toml /app/
COPY README.md /app/

# uv でインストール
RUN pip install uv && \
    cd /app && \
    uv pip install --system -e .

# アプリケーションコードをコピー
COPY common /app/common
COPY services/shopping_agent_mcp /app/services/shopping_agent_mcp

# ポート公開
EXPOSE 8010

# サービス起動
CMD ["uvicorn", "services.shopping_agent_mcp.main:app", "--host", "0.0.0.0", "--port", "8010"]
