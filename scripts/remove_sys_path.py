#!/usr/bin/env python3
"""
v2/ディレクトリの不要なsys.path操作を削除するスクリプト

目的:
- sys.path.insert()、sys.path.append()を削除
- v2/を完全に独立したパッケージにする

使用方法:
    python v2/scripts/remove_sys_path.py --dry-run  # プレビュー
    python v2/scripts/remove_sys_path.py            # 実行
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple


class SysPathRemover:
    """sys.path操作を削除するクラス"""

    def __init__(self, base_dir: Path, dry_run: bool = False):
        self.base_dir = base_dir
        self.dry_run = dry_run
        self.stats = {
            "files_scanned": 0,
            "files_modified": 0,
            "sys_path_removed": 0
        }

    def remove_sys_path_in_file(self, file_path: Path) -> Tuple[bool, List[str]]:
        """
        ファイル内のsys.path操作を削除

        Args:
            file_path: Pythonファイルのパス

        Returns:
            (modified, changes): 変更があったか、変更内容のリスト
        """
        try:
            content = file_path.read_text(encoding='utf-8')
            original_content = content
            changes = []
            lines = content.split('\n')
            new_lines = []
            skip_next_blank = False

            for i, line in enumerate(lines):
                # sys.path操作の行を検出
                if re.match(r'^\s*sys\.path\.(insert|append)\s*\(', line):
                    # テストファイルは除外（test_*.pyファイルは残す）
                    if file_path.name.startswith('test_'):
                        new_lines.append(line)
                        continue

                    # コメントを確認
                    prev_line_idx = i - 1
                    while prev_line_idx >= 0 and (
                        lines[prev_line_idx].strip().startswith('#') or
                        lines[prev_line_idx].strip() == ''
                    ):
                        if lines[prev_line_idx].strip().startswith('#'):
                            # コメント行も削除対象に含める
                            if '親ディレクトリ' in lines[prev_line_idx] or 'sys.path' in lines[prev_line_idx]:
                                prev_line_idx -= 1
                                continue
                        prev_line_idx -= 1

                    # 削除対象の行数をカウント
                    removed_comment_lines = i - prev_line_idx - 1
                    if removed_comment_lines > 0:
                        # コメント行も削除
                        for _ in range(removed_comment_lines):
                            if new_lines and (new_lines[-1].strip().startswith('#') or new_lines[-1].strip() == ''):
                                new_lines.pop()

                    changes.append(f"  - Line {i+1}: sys.path操作を削除")
                    self.stats["sys_path_removed"] += 1
                    skip_next_blank = True
                    continue

                # 直後の空行を1つだけスキップ
                if skip_next_blank and line.strip() == '':
                    skip_next_blank = False
                    continue

                new_lines.append(line)

            new_content = '\n'.join(new_lines)

            # 変更があったか確認
            modified = new_content != original_content

            if modified and not self.dry_run:
                file_path.write_text(new_content, encoding='utf-8')

            return modified, changes

        except Exception as e:
            print(f"❌ エラー: {file_path}: {e}")
            return False, []

    def scan_and_remove(self):
        """v2/ディレクトリ内のすべての.pyファイルをスキャン・修正"""
        print(f"{'=' * 60}")
        print(f"v2/ ディレクトリのsys.path操作削除スクリプト")
        print(f"モード: {'ドライラン（プレビューのみ）' if self.dry_run else '実行'}")
        print(f"{'=' * 60}\n")

        # .pyファイルを検索
        py_files = list(self.base_dir.rglob("*.py"))

        # __pycache__と.venvを除外
        py_files = [f for f in py_files if "__pycache__" not in str(f) and ".venv" not in str(f)]

        print(f"📂 スキャン対象: {len(py_files)}ファイル\n")

        # 各ファイルを処理
        modified_files = []

        for py_file in sorted(py_files):
            self.stats["files_scanned"] += 1
            rel_path = py_file.relative_to(self.base_dir)

            modified, changes = self.remove_sys_path_in_file(py_file)

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
        print(f"削除したsys.path操作: {self.stats['sys_path_removed']}")

        if self.dry_run:
            print(f"\n⚠️  ドライランモード: 実際のファイルは変更されていません")
            print(f"実行するには --dry-run オプションを外してください")
        else:
            print(f"\n✅ 変更を適用しました！")
            print(f"\n📝 注意: テストファイル（test_*.py）のsys.path操作は保持されています")

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

    # 削除実行
    remover = SysPathRemover(v2_dir, dry_run=dry_run)
    remover.scan_and_remove()


if __name__ == "__main__":
    main()
