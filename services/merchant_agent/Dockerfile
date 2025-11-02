# Merchant Agent Dockerfile

FROM python:3.11-slim

WORKDIR /app

# システム依存関係のインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# uvをインストール
RUN pip install uv

# プロジェクトファイルをコピー
COPY pyproject.toml /app/
COPY README.md /app/
COPY common /app/common
COPY services/merchant_agent /app/services/merchant_agent

# 依存関係をインストール（uvを使用）
RUN cd /app && uv pip install --system -e .

# ポート公開
EXPOSE 8001

# Merchant Agent起動
CMD ["uvicorn", "services.merchant_agent.main:app", "--host", "0.0.0.0", "--port", "8001"]
