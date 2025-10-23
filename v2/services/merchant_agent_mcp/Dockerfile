FROM python:3.12-slim

WORKDIR /app

# システムパッケージ更新
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 依存関係をコピー
COPY v2/pyproject.toml /app/v2/
COPY v2/README.md /app/v2/

# uv でインストール
RUN pip install uv && \
    cd /app/v2 && \
    uv pip install --system -e .

# アプリケーションコードをコピー
COPY v2/common /app/v2/common
COPY v2/services/merchant_agent_mcp /app/v2/services/merchant_agent_mcp

# 作業ディレクトリ設定
WORKDIR /app/v2/services/merchant_agent_mcp

# ポート公開
EXPOSE 8011

# サービス起動
CMD ["python", "main.py"]
