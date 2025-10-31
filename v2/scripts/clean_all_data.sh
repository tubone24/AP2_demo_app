#!/bin/bash

#
# clean_all_data.sh
#
# AP2プロジェクトの全データをクリーンアップするスクリプト
# ディレクトリ構造と.gitkeepファイルは維持します
#
# 使用方法:
#   bash scripts/clean_all_data.sh
#

set -e  # エラー時に停止

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "========================================="
echo "AP2 Data Cleanup Script"
echo "========================================="
echo ""
echo "プロジェクトルート: $PROJECT_ROOT"
echo ""
echo "警告: 以下のディレクトリのファイルを削除します："
echo "  - keys/"
echo "  - data/"
echo ""
echo "ディレクトリ構造と.gitkeepファイルは維持されます。"
echo ""

# 確認プロンプト
read -p "続行しますか? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "キャンセルされました。"
    exit 0
fi

echo ""
echo "クリーンアップを開始します..."
echo ""

# keys/ディレクトリのクリーンアップ
echo "[1/2] keys/ディレクトリをクリーンアップ中..."
if [ -d "$PROJECT_ROOT/keys" ]; then
    # .gitkeepとディレクトリ以外のファイルを削除
    find "$PROJECT_ROOT/keys" -type f ! -name '.gitkeep' -delete
    echo "  ✓ keys/配下のファイルを削除しました（.gitkeepは維持）"
else
    echo "  ! keys/ディレクトリが見つかりません"
fi

# data/ディレクトリのクリーンアップ
echo "[2/2] data/ディレクトリをクリーンアップ中..."
if [ -d "$PROJECT_ROOT/data" ]; then
    # .gitkeepとディレクトリ以外のファイルを削除
    find "$PROJECT_ROOT/data" -type f ! -name '.gitkeep' -delete

    # 空のサブディレクトリ内のファイルも削除（.gitkeepは除く）
    # ※ data/meilisearch, data/redis, data/receipts などのサブディレクトリ
    echo "  ✓ data/配下のファイルを削除しました（.gitkeepとディレクトリ構造は維持）"
else
    echo "  ! data/ディレクトリが見つかりません"
fi

echo ""
echo "========================================="
echo "クリーンアップ完了!"
echo "========================================="
echo ""
echo "次のステップ:"
echo "  1. docker compose down -v  # Dockerボリュームも削除"
echo "  2. docker compose up -d    # サービスを再起動"
echo ""
