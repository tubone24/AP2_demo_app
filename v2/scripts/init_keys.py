#!/usr/bin/env python3
"""
v2/scripts/init_keys.py

AP2エージェントのキーペア初期化スクリプト

このスクリプトは、各エージェントの秘密鍵・公開鍵ペアを生成し、
永続化ストレージに保存します。これにより、コンテナ再起動時も
同じDIDを維持できます。

セキュリティ要件：
1. 秘密鍵は環境変数のパスフレーズで暗号化して保存
2. 公開鍵はDID Documentに含めて公開
3. RFC 8785準拠のJSON正規化を使用
4. ECDSA SECP256R1 (ES256) を使用（crypto.pyとの互換性）

使用方法：
    python v2/scripts/init_keys.py

必須環境変数：
    AP2_SHOPPING_AGENT_PASSPHRASE
    AP2_MERCHANT_AGENT_PASSPHRASE
    AP2_MERCHANT_PASSPHRASE
    AP2_CREDENTIAL_PROVIDER_PASSPHRASE
    AP2_PAYMENT_PROCESSOR_PASSPHRASE
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend


# エージェント定義
# 注意: ユーザーの鍵はWebAuthn/Passkeyでデバイス側で管理されるため、
#      サーバー側では生成しない（AP2仕様準拠）
AGENTS = [
    {
        "agent_id": "shopping_agent",
        "did": "did:ap2:agent:shopping_agent",
        "name": "Shopping Agent",
        "env_var": "AP2_SHOPPING_AGENT_PASSPHRASE"
    },
    {
        "agent_id": "merchant_agent",
        "did": "did:ap2:agent:merchant_agent",
        "name": "Merchant Agent",
        "env_var": "AP2_MERCHANT_AGENT_PASSPHRASE"
    },
    {
        "agent_id": "merchant",
        "did": "did:ap2:merchant:mugibo_merchant",
        "name": "Merchant",
        "env_var": "AP2_MERCHANT_PASSPHRASE"
    },
    {
        "agent_id": "credential_provider",
        "did": "did:ap2:cp:demo_cp",
        "name": "Credential Provider",
        "env_var": "AP2_CREDENTIAL_PROVIDER_PASSPHRASE"
    },
    {
        "agent_id": "payment_processor",
        "did": "did:ap2:agent:payment_processor",
        "name": "Payment Processor",
        "env_var": "AP2_PAYMENT_PROCESSOR_PASSPHRASE"
    }
]

# キー保存ディレクトリ（Docker Volumeマウント想定）
KEYS_DIR = Path("/app/v2/keys")
DID_DOCS_DIR = Path("/app/v2/data/did_documents")


class KeyInitializer:
    """キーペア初期化クラス"""

    def __init__(self):
        """初期化"""
        # ディレクトリ作成
        KEYS_DIR.mkdir(parents=True, exist_ok=True)
        DID_DOCS_DIR.mkdir(parents=True, exist_ok=True)

    def generate_ecdsa_keypair(self, curve=ec.SECP256R1()) -> tuple:
        """
        ECDSA SECP256R1キーペアを生成

        Args:
            curve: 楕円曲線（デフォルト: SECP256R1 / P-256）

        Returns:
            (private_key, public_key): 秘密鍵と公開鍵のタプル
        """
        private_key = ec.generate_private_key(curve, default_backend())
        public_key = private_key.public_key()
        return private_key, public_key

    def generate_ed25519_keypair(self) -> tuple:
        """
        Ed25519キーペアを生成（A2A通信用）

        Returns:
            (private_key, public_key): Ed25519秘密鍵と公開鍵のタプル
        """
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        return private_key, public_key

    def encrypt_private_key(self, private_key, passphrase: str) -> bytes:
        """
        秘密鍵をAES-256-CBCで暗号化（crypto.py互換、ECDSA/Ed25519両対応）

        Args:
            private_key: ECDSA or Ed25519秘密鍵
            passphrase: 暗号化パスフレーズ

        Returns:
            暗号化されたPEM形式の秘密鍵
        """
        # crypto.pyと同じ方式で暗号化（BestAvailableEncryption）
        encrypted_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(
                passphrase.encode('utf-8')
            )
        )

        return encrypted_pem

    def save_private_key(self, agent_id: str, encrypted_pem: bytes):
        """
        暗号化された秘密鍵をファイルに保存（crypto.py互換）

        Args:
            agent_id: エージェントID
            encrypted_pem: 暗号化されたPEM形式の秘密鍵
        """
        key_file = KEYS_DIR / f"{agent_id}_private.pem"
        key_file.write_bytes(encrypted_pem)

        # パーミッションを制限（所有者のみ読み書き可能）
        os.chmod(key_file, 0o600)

        print(f"  ✓ 秘密鍵を保存: {key_file}")

    def save_public_key(self, agent_id: str, public_key, suffix: str = ""):
        """
        公開鍵をPEM形式でファイルに保存（crypto.py互換、ECDSA/Ed25519両対応）

        Args:
            agent_id: エージェントID
            public_key: ECDSA or Ed25519公開鍵
            suffix: ファイル名サフィックス（例: "_ed25519"）
        """
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        key_file = KEYS_DIR / f"{agent_id}{suffix}_public.pem"
        key_file.write_bytes(public_pem)
        print(f"  ✓ 公開鍵を保存: {key_file}")

    def create_did_document(self, agent_info: Dict[str, Any], ecdsa_public_key: ec.EllipticCurvePublicKey, ed25519_public_key) -> Dict[str, Any]:
        """
        W3C DID準拠のDID Documentを生成（ECDSA + Ed25519の両方の鍵を含む）

        Args:
            agent_info: エージェント情報
            ecdsa_public_key: ECDSA公開鍵（JWT署名用）
            ed25519_public_key: Ed25519公開鍵（A2A通信用）

        Returns:
            DID Document
        """
        did = agent_info["did"]

        # ECDSA公開鍵のPEM
        ecdsa_pem = ecdsa_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        # Ed25519公開鍵のPEM
        ed25519_pem = ed25519_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        did_doc = {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/jws-2020/v1",
                "https://w3id.org/security/suites/ed25519-2020/v1"
            ],
            "id": did,
            "verificationMethod": [
                {
                    "id": f"{did}#key-1",
                    "type": "EcdsaSecp256r1VerificationKey2019",
                    "controller": did,
                    "publicKeyPem": ecdsa_pem
                },
                {
                    "id": f"{did}#key-2",
                    "type": "Ed25519VerificationKey2020",
                    "controller": did,
                    "publicKeyPem": ed25519_pem
                }
            ],
            "authentication": [f"{did}#key-1", f"{did}#key-2"],
            "assertionMethod": [f"{did}#key-1", f"{did}#key-2"],
            "created": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

        return did_doc

    def save_did_document(self, agent_id: str, did_doc: Dict[str, Any]):
        """
        DID DocumentをJSONファイルに保存

        Args:
            agent_id: エージェントID
            did_doc: DID Document
        """
        did_file = DID_DOCS_DIR / f"{agent_id}_did.json"
        did_file.write_text(json.dumps(did_doc, indent=2, ensure_ascii=False))
        print(f"  ✓ DID Documentを保存: {did_file}")

    def initialize_agent(self, agent_info: Dict[str, Any]):
        """
        エージェントのキーペアとDID Documentを初期化

        Args:
            agent_info: エージェント情報
        """
        agent_id = agent_info["agent_id"]
        env_var = agent_info["env_var"]

        print(f"\n[{agent_info['name']}]")

        # パスフレーズを環境変数から取得
        passphrase = os.getenv(env_var)
        if not passphrase:
            raise RuntimeError(
                f"❌ 環境変数 {env_var} が設定されていません。\n"
                f"   セキュリティのため、パスフレーズは必須です。"
            )

        # 既存の鍵をチェック（crypto.py互換のファイル名）
        private_key_file = KEYS_DIR / f"{agent_id}_private.pem"
        public_key_file = KEYS_DIR / f"{agent_id}_public.pem"
        did_doc_file = DID_DOCS_DIR / f"{agent_id}_did.json"

        if private_key_file.exists() and public_key_file.exists() and did_doc_file.exists():
            print(f"  ℹ️  既存の鍵とDID Documentが見つかりました（スキップ）")
            print(f"     DID: {agent_info['did']}")
            return

        # 新規にECDSAキーペアを生成（JWT署名用）
        print(f"  🔑 ECDSA SECP256R1キーペアを生成中（JWT用）...")
        ecdsa_private_key, ecdsa_public_key = self.generate_ecdsa_keypair()

        # ECDSA秘密鍵を暗号化
        print(f"  🔒 ECDSA秘密鍵をAES-256-CBCで暗号化中...")
        ecdsa_encrypted_key = self.encrypt_private_key(ecdsa_private_key, passphrase)

        # ECDSAファイルに保存
        self.save_private_key(agent_id, ecdsa_encrypted_key)
        self.save_public_key(agent_id, ecdsa_public_key)

        # 新規にEd25519キーペアを生成（A2A通信用）
        print(f"  🔑 Ed25519キーペアを生成中（A2A通信用）...")
        ed25519_private_key, ed25519_public_key = self.generate_ed25519_keypair()

        # Ed25519秘密鍵を暗号化
        print(f"  🔒 Ed25519秘密鍵をAES-256-CBCで暗号化中...")
        ed25519_encrypted_key = self.encrypt_private_key(ed25519_private_key, passphrase)

        # Ed25519ファイルに保存（crypto.pyと互換性のあるファイル名）
        ed25519_private_file = KEYS_DIR / f"{agent_id}_ed25519_private.pem"
        ed25519_private_file.write_bytes(ed25519_encrypted_key)
        os.chmod(ed25519_private_file, 0o600)
        print(f"  ✓ Ed25519秘密鍵を保存: {ed25519_private_file}")

        self.save_public_key(agent_id, ed25519_public_key, suffix="_ed25519")

        # DID Documentを生成（ECDSA + Ed25519両方の公開鍵を含む）
        print(f"  📄 W3C準拠のDID Documentを生成中（ECDSA + Ed25519）...")
        did_doc = self.create_did_document(agent_info, ecdsa_public_key, ed25519_public_key)
        self.save_did_document(agent_id, did_doc)

        print(f"  ✅ 初期化完了: DID = {agent_info['did']}")

    def run(self):
        """全エージェントのキーを初期化"""
        print("="*80)
        print("AP2 エージェント キーペア初期化")
        print("="*80)
        print(f"\nキー保存先: {KEYS_DIR}")
        print(f"DID Document保存先: {DID_DOCS_DIR}")

        for agent_info in AGENTS:
            try:
                self.initialize_agent(agent_info)
            except Exception as e:
                print(f"\n❌ エラー: {agent_info['name']} の初期化に失敗しました")
                print(f"   {e}")
                sys.exit(1)

        print("\n" + "="*80)
        print("✅ 全エージェントの初期化が完了しました")
        print("="*80)
        print("\n次のステップ:")
        print("  1. docker-compose up -d でサービスを起動")
        print("  2. 各エージェントはキーを永続化ストレージから読み込みます")
        print("  3. DIDは再起動後も一貫して維持されます")
        print()


if __name__ == "__main__":
    initializer = KeyInitializer()
    initializer.run()
