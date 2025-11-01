# AP2 Scripts

このディレクトリには、AP2プロジェクトの管理スクリプトが含まれています。

## clean_all_data.sh

全データをクリーンアップするスクリプトです。

### 機能

- `keys/`配下のファイルを削除（.gitkeepとディレクトリ構造は維持）
- `data/`配下のファイルを削除（.gitkeepとディレクトリ構造は維持）

### 使用方法

```bash
# v2ディレクトリから実行
cd /Users/kagadminmac/project/ap2/v2
bash scripts/clean_all_data.sh
```

### データリセット手順（完全な初期化）

1. **データクリーンアップ**
   ```bash
   bash scripts/clean_all_data.sh
   ```

2. **Dockerコンテナとボリュームを停止・削除**
   ```bash
   docker compose down -v
   ```

3. **サービスを再起動**
   ```bash
   docker compose up -d
   ```

4. **ログを確認**
   ```bash
   docker compose logs -f
   ```

### 注意事項

- このスクリプトは**データを完全に削除**します
- 実行前に重要なデータがないことを確認してください
- 確認プロンプトで `y` を入力する必要があります
- ディレクトリ構造と `.gitkeep` ファイルは保持されます

## init_db.py

データベースを初期化するスクリプトです。

### 使用方法

```bash
python scripts/init_db.py
```

## init_keys.py

暗号鍵を初期化するスクリプトです。

### 使用方法

```bash
python scripts/init_keys.py
```

## init_seeds.py

シードデータを投入するスクリプトです。

### 使用方法

```bash
python scripts/init_seeds.py
```
