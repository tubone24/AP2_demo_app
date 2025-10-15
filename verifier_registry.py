"""
AP2 Protocol - Verifier公開鍵管理
署名検証者が信頼できる公開鍵を管理する機能
"""

from typing import Dict, Optional, List, Set
from datetime import datetime, timezone
from dataclasses import dataclass
import json
from pathlib import Path

from ap2_types import AgentType, AgentIdentity


@dataclass
class TrustedPublicKey:
    """
    信頼された公開鍵の情報
    """
    entity_id: str  # エンティティID（user_id, merchant_id, agent_idなど）
    entity_name: str  # エンティティ名
    entity_type: str  # エンティティタイプ（"user", "merchant", "agent"など）
    public_key: str  # Base64エンコードされた公開鍵
    added_at: str  # 登録日時（ISO 8601）
    added_by: str  # 登録者
    is_active: bool = True  # アクティブかどうか
    metadata: Optional[Dict] = None  # 追加のメタデータ


class VerifierPublicKeyRegistry:
    """
    Verifier（検証者）公開鍵レジストリ

    署名検証時に、署名者の公開鍵が信頼できるものかどうかを確認するための
    公開鍵レジストリ。検証者は事前に信頼できるエンティティの公開鍵を登録し、
    署名検証時にこのレジストリを参照する。
    """

    def __init__(self, registry_file: str = "./verifier_registry.json"):
        """
        Args:
            registry_file: レジストリファイルのパス
        """
        self.registry_file = Path(registry_file)
        self.trusted_keys: Dict[str, TrustedPublicKey] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """レジストリファイルから公開鍵を読み込む"""
        if self.registry_file.exists():
            try:
                with open(self.registry_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for entity_id, key_data in data.items():
                        self.trusted_keys[entity_id] = TrustedPublicKey(**key_data)
                print(f"[VerifierRegistry] レジストリを読み込みました: {len(self.trusted_keys)}件")
            except Exception as e:
                print(f"[VerifierRegistry] レジストリの読み込みに失敗しました: {e}")
                self.trusted_keys = {}
        else:
            print(f"[VerifierRegistry] 新しいレジストリを作成します")
            self.trusted_keys = {}

    def _save_registry(self) -> None:
        """レジストリファイルに公開鍵を保存"""
        try:
            # ディレクトリが存在しない場合は作成
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)

            # TrustedPublicKeyをdictに変換
            data = {}
            for entity_id, trusted_key in self.trusted_keys.items():
                data[entity_id] = {
                    "entity_id": trusted_key.entity_id,
                    "entity_name": trusted_key.entity_name,
                    "entity_type": trusted_key.entity_type,
                    "public_key": trusted_key.public_key,
                    "added_at": trusted_key.added_at,
                    "added_by": trusted_key.added_by,
                    "is_active": trusted_key.is_active,
                    "metadata": trusted_key.metadata
                }

            with open(self.registry_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[VerifierRegistry] レジストリを保存しました: {len(self.trusted_keys)}件")
        except Exception as e:
            print(f"[VerifierRegistry] レジストリの保存に失敗しました: {e}")

    def register_public_key(
        self,
        entity_id: str,
        entity_name: str,
        entity_type: str,
        public_key: str,
        added_by: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        信頼できる公開鍵を登録

        Args:
            entity_id: エンティティID
            entity_name: エンティティ名
            entity_type: エンティティタイプ
            public_key: Base64エンコードされた公開鍵
            added_by: 登録者
            metadata: 追加のメタデータ
        """
        trusted_key = TrustedPublicKey(
            entity_id=entity_id,
            entity_name=entity_name,
            entity_type=entity_type,
            public_key=public_key,
            added_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            added_by=added_by,
            is_active=True,
            metadata=metadata
        )

        self.trusted_keys[entity_id] = trusted_key
        self._save_registry()

        print(f"[VerifierRegistry] 公開鍵を登録しました: {entity_id} ({entity_name})")

    def is_public_key_trusted(self, entity_id: str, public_key: str) -> bool:
        """
        公開鍵が信頼できるかどうかを確認

        Args:
            entity_id: エンティティID
            public_key: 検証する公開鍵（Base64）

        Returns:
            bool: 信頼できる場合はTrue
        """
        if entity_id not in self.trusted_keys:
            print(f"[VerifierRegistry] エンティティが登録されていません: {entity_id}")
            return False

        trusted_key = self.trusted_keys[entity_id]

        if not trusted_key.is_active:
            print(f"[VerifierRegistry] エンティティが無効化されています: {entity_id}")
            return False

        if trusted_key.public_key != public_key:
            print(f"[VerifierRegistry] 公開鍵が一致しません: {entity_id}")
            return False

        return True

    def revoke_public_key(self, entity_id: str, revoked_by: str) -> bool:
        """
        公開鍵を無効化（取り消し）

        Args:
            entity_id: 無効化するエンティティID
            revoked_by: 無効化を実行した者

        Returns:
            bool: 成功した場合はTrue
        """
        if entity_id not in self.trusted_keys:
            print(f"[VerifierRegistry] エンティティが見つかりません: {entity_id}")
            return False

        self.trusted_keys[entity_id].is_active = False
        if self.trusted_keys[entity_id].metadata is None:
            self.trusted_keys[entity_id].metadata = {}
        self.trusted_keys[entity_id].metadata['revoked_by'] = revoked_by
        self.trusted_keys[entity_id].metadata['revoked_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        self._save_registry()

        print(f"[VerifierRegistry] 公開鍵を無効化しました: {entity_id}")
        return True

    def get_trusted_key(self, entity_id: str) -> Optional[TrustedPublicKey]:
        """
        信頼された公開鍵情報を取得

        Args:
            entity_id: エンティティID

        Returns:
            Optional[TrustedPublicKey]: 公開鍵情報（見つからない場合はNone）
        """
        return self.trusted_keys.get(entity_id)

    def list_trusted_keys(
        self,
        entity_type: Optional[str] = None,
        active_only: bool = True
    ) -> List[TrustedPublicKey]:
        """
        信頼された公開鍵のリストを取得

        Args:
            entity_type: フィルター用エンティティタイプ（Noneの場合は全て）
            active_only: アクティブな公開鍵のみを取得するか

        Returns:
            List[TrustedPublicKey]: 公開鍵情報のリスト
        """
        keys = list(self.trusted_keys.values())

        if entity_type:
            keys = [k for k in keys if k.entity_type == entity_type]

        if active_only:
            keys = [k for k in keys if k.is_active]

        return keys

    def register_agent_identity(self, agent_identity: AgentIdentity, added_by: str) -> None:
        """
        AgentIdentityから公開鍵を登録

        Args:
            agent_identity: エージェントの識別情報
            added_by: 登録者
        """
        self.register_public_key(
            entity_id=agent_identity.id,
            entity_name=agent_identity.name,
            entity_type=f"agent_{agent_identity.type.value}",
            public_key=agent_identity.public_key,
            added_by=added_by,
            metadata={
                "agent_type": agent_identity.type.value
            }
        )


def demo_verifier_registry():
    """Verifier公開鍵レジストリのデモ"""
    print("=" * 80)
    print("AP2 Protocol - Verifier公開鍵レジストリのデモ")
    print("=" * 80)

    # レジストリを初期化
    registry = VerifierPublicKeyRegistry("./demo_verifier_registry.json")

    # ユーザーの公開鍵を登録
    print("\n--- ユーザー公開鍵の登録 ---")
    registry.register_public_key(
        entity_id="user_001",
        entity_name="Alice",
        entity_type="user",
        public_key="LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0...",  # ダミー
        added_by="system_admin"
    )

    # マーチャントの公開鍵を登録
    print("\n--- マーチャント公開鍵の登録 ---")
    registry.register_public_key(
        entity_id="merchant_001",
        entity_name="Running Shoes Store",
        entity_type="merchant",
        public_key="LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS1...",  # ダミー
        added_by="system_admin",
        metadata={"store_type": "e-commerce"}
    )

    # Shopping Agentの公開鍵を登録
    print("\n--- Shopping Agent公開鍵の登録 ---")
    registry.register_public_key(
        entity_id="shopping_agent_001",
        entity_name="Secure Shopping Assistant",
        entity_type="agent_shopping",
        public_key="LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS1...",  # ダミー
        added_by="system_admin"
    )

    # 公開鍵の検証
    print("\n--- 公開鍵の検証 ---")
    is_trusted = registry.is_public_key_trusted(
        "user_001",
        "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS0..."
    )
    print(f"user_001の公開鍵が信頼できるか: {is_trusted}")

    # 不正な公開鍵での検証
    is_trusted_fake = registry.is_public_key_trusted(
        "user_001",
        "FAKE_PUBLIC_KEY_XXX"
    )
    print(f"不正な公開鍵での検証: {is_trusted_fake}")

    # 信頼された公開鍵のリスト表示
    print("\n--- 信頼された公開鍵のリスト ---")
    all_keys = registry.list_trusted_keys()
    for key in all_keys:
        print(f"  - {key.entity_id} ({key.entity_name}) [{key.entity_type}]")

    # 公開鍵の無効化
    print("\n--- 公開鍵の無効化 ---")
    registry.revoke_public_key("merchant_001", "security_team")

    # 無効化後の検証
    is_trusted_after_revoke = registry.is_public_key_trusted(
        "merchant_001",
        "LS0tLS1CRUdJTiBQVUJMSUMgS0VZLS0tLS1..."
    )
    print(f"merchant_001の公開鍵（無効化後）: {is_trusted_after_revoke}")

    # アクティブな公開鍵のみ表示
    print("\n--- アクティブな公開鍵のリスト ---")
    active_keys = registry.list_trusted_keys(active_only=True)
    for key in active_keys:
        print(f"  - {key.entity_id} ({key.entity_name}) [{key.entity_type}]")

    print("\n" + "=" * 80)
    print("デモンストレーション完了!")
    print("=" * 80)


if __name__ == "__main__":
    demo_verifier_registry()