FROM python:3.11-slim

WORKDIR /app

# システム依存関係のインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# uvをインストール
RUN pip install uv

# プロジェクトファイルをコピー
COPY v2/pyproject.toml /app/v2/
COPY v2/README.md /app/v2/
COPY v2/services/payment_network /app/v2/services/payment_network

# 依存関係をインストール（uvを使用）
RUN cd /app/v2 && uv pip install --system -e .

# ワーキングディレクトリを設定
WORKDIR /app/v2/services/payment_network

# ポート公開
EXPOSE 8005

# サービス起動
CMD ["python", "main.py"]
