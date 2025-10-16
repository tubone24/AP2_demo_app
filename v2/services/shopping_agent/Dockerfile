# Shopping Agent Dockerfile

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
COPY v2/common /app/v2/common
COPY v2/services/shopping_agent /app/v2/services/shopping_agent

# 既存のap2_crypto.pyとap2_types.pyをコピー
COPY ap2_crypto.py /app/
COPY ap2_types.py /app/

# 依存関係をインストール（uvを使用）
RUN cd /app/v2 && uv pip install --system -e .

# ワーキングディレクトリを設定
WORKDIR /app/v2/services/shopping_agent

# ポート公開
EXPOSE 8000

# Shopping Agent起動
CMD ["python", "main.py"]
