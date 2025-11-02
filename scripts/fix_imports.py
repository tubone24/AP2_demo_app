#!/usr/bin/env python3
"""
v2/ディレクトリのimportを修正するスクリプト

目的:
- すべての `from v2.xxx` を `from xxx` に変更
- v2/を完全に独立したパッケージにする

使用方法:
    python v2/scripts/fix_imports.py --dry-run  # プレビュー
    python v2/scripts/fix_imports.py            # 実行
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


class ImportFixer:
    """importパターンを修正するクラス"""

    def __init__(self, base_dir: Path, dry_run: bool = False):
        self.base_dir = base_dir
        self.dry_run = dry_run
        self.stats = {
            "files_scanned": 0,
            "files_modified": 0,
            "imports_fixed": 0,
            "sys_path_removed": 0
        }

    def fix_imports_in_file(self, file_path: Path) -> Tuple[bool, List[str]]:
        """
        ファイル内のimportを修正

        Args:
            file_path: Pythonファイルのパス

        Returns:
            (modified, changes): 変更があったか、変更内容のリスト
        """
        try:
            content = file_path.read_text(encoding='utf-8')
            original_content = content
            changes = []

            # パターン1: from v2.xxx import yyy
            pattern1 = r'from v2\.(common|services|scripts)\b'
            replacement1 = r'from \1'
            new_content, count1 = re.subn(pattern1, replacement1, content)
            if count1 > 0:
                changes.append(f"  - from v2.xxx → from xxx ({count1}箇所)")
                self.stats["imports_fixed"] += count1
            content = new_content

            # パターン2: import v2.xxx
            pattern2 = r'import v2\.(common|services|scripts)\b'
            replacement2 = r'import \1'
            new_content, count2 = re.subn(pattern2, replacement2, content)
            if count2 > 0:
                changes.append(f"  - import v2.xxx → import xxx ({count2}箇所)")
                self.stats["imports_fixed"] += count2
            content = new_content

            # 変更があったか確認
            modified = content != original_content

            if modified and not self.dry_run:
                file_path.write_text(content, encoding='utf-8')

            return modified, changes

        except Exception as e:
            print(f"❌ エラー: {file_path}: {e}")
            return False, []

    def scan_and_fix(self):
        """v2/ディレクトリ内のすべての.pyファイルをスキャン・修正"""
        print(f"{'=' * 60}")
        print(f"v2/ ディレクトリのimport修正スクリプト")
        print(f"モード: {'ドライラン（プレビューのみ）' if self.dry_run else '実行'}")
        print(f"{'=' * 60}\n")

        # .pyファイルを検索
        py_files = list(self.base_dir.rglob("*.py"))

        # __pycache__を除外
        py_files = [f for f in py_files if "__pycache__" not in str(f)]

        print(f"📂 スキャン対象: {len(py_files)}ファイル\n")

        # 各ファイルを処理
        modified_files = []

        for py_file in sorted(py_files):
            self.stats["files_scanned"] += 1
            rel_path = py_file.relative_to(self.base_dir)

            modified, changes = self.fix_imports_in_file(py_file)

            if modified:
                self.stats["files_modified"] += 1
                modified_files.append((rel_path, changes))
                status = "🔧" if not self.dry_run else "👁️ "
                print(f"{status} {rel_path}")
                for change in changes:
                    print(change)
                print()

        # 結果サマリー
        print(f"\n{'=' * 60}")
        print(f"📊 結果サマリー")
        print(f"{'=' * 60}")
        print(f"スキャンしたファイル: {self.stats['files_scanned']}")
        print(f"変更したファイル: {self.stats['files_modified']}")
        print(f"修正したimport: {self.stats['imports_fixed']}")

        if self.dry_run:
            print(f"\n⚠️  ドライランモード: 実際のファイルは変更されていません")
            print(f"実行するには --dry-run オプションを外してください")
        else:
            print(f"\n✅ 変更を適用しました！")

        return modified_files


def main():
    """メイン関数"""
    # 引数解析
    dry_run = "--dry-run" in sys.argv

    # v2/ディレクトリのパス
    script_dir = Path(__file__).parent
    v2_dir = script_dir.parent

    if not v2_dir.exists():
        print(f"❌ エラー: v2/ディレクトリが見つかりません: {v2_dir}")
        sys.exit(1)

    # 修正実行
    fixer = ImportFixer(v2_dir, dry_run=dry_run)
    fixer.scan_and_fix()


if __name__ == "__main__":
    main()
