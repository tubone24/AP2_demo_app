"""
AP2 Protocol - 暗号署名と鍵管理の実装
実際の暗号ライブラリを使用したセキュアな実装
"""

import json
import base64
import hashlib
import os
from typing import Tuple, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature

from ap2_types import Signature


class CryptoError(Exception):
    """暗号処理に関するエラー"""
    pass


class KeyManager:
    """
    鍵管理クラス
    秘密鍵の生成、保存、読み込み、暗号化を管理
    """
    
    def __init__(self, keys_directory: str = "./keys"):
        """
        Args:
            keys_directory: 鍵を保存するディレクトリ
        """
        self.keys_directory = Path(keys_directory)
        self.keys_directory.mkdir(parents=True, exist_ok=True)
        self.backend = default_backend()
        
        # アクティブな鍵（メモリ上）
        self._active_keys: Dict[str, ec.EllipticCurvePrivateKey] = {}
    
    def generate_key_pair(
        self,
        key_id: str,
        curve: ec.EllipticCurve = ec.SECP256R1()
    ) -> Tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
        """
        新しい鍵ペアを生成
        
        Args:
            key_id: 鍵の識別子
            curve: 楕円曲線（デフォルト: SECP256R1 / P-256）
            
        Returns:
            Tuple[秘密鍵, 公開鍵]
        """
        print(f"[KeyManager] 新しい鍵ペアを生成: {key_id}")
        
        # 秘密鍵を生成
        private_key = ec.generate_private_key(curve, self.backend)
        public_key = private_key.public_key()
        
        # メモリに保存
        self._active_keys[key_id] = private_key
        
        print(f"  ✓ 鍵ペア生成完了（曲線: {curve.name}）")
        return private_key, public_key
    
    def save_private_key_encrypted(
        self,
        key_id: str,
        private_key: ec.EllipticCurvePrivateKey,
        passphrase: str
    ) -> str:
        """
        秘密鍵をパスフレーズで暗号化して保存
        
        Args:
            key_id: 鍵の識別子
            private_key: 秘密鍵
            passphrase: パスフレーズ
            
        Returns:
            str: 保存先のファイルパス
        """
        print(f"[KeyManager] 秘密鍵を暗号化して保存: {key_id}")
        
        # 秘密鍵をPEMフォーマットでシリアライズ（暗号化）
        encrypted_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(
                passphrase.encode('utf-8')
            )
        )
        
        # ファイルに保存
        key_file = self.keys_directory / f"{key_id}_private.pem"
        key_file.write_bytes(encrypted_pem)
        
        # パーミッションを制限（所有者のみ読み書き可能）
        os.chmod(key_file, 0o600)
        
        print(f"  ✓ 秘密鍵を保存: {key_file}")
        print(f"  ✓ パーミッション: 0o600（所有者のみアクセス可能）")
        
        return str(key_file)
    
    def load_private_key_encrypted(
        self,
        key_id: str,
        passphrase: str
    ) -> ec.EllipticCurvePrivateKey:
        """
        暗号化された秘密鍵を読み込み
        
        Args:
            key_id: 鍵の識別子
            passphrase: パスフレーズ
            
        Returns:
            ec.EllipticCurvePrivateKey: 秘密鍵
        """
        print(f"[KeyManager] 秘密鍵を読み込み: {key_id}")
        
        key_file = self.keys_directory / f"{key_id}_private.pem"
        
        if not key_file.exists():
            raise CryptoError(f"秘密鍵ファイルが見つかりません: {key_file}")
        
        # ファイルから読み込み
        encrypted_pem = key_file.read_bytes()
        
        try:
            # 復号化して秘密鍵をロード
            private_key = serialization.load_pem_private_key(
                encrypted_pem,
                password=passphrase.encode('utf-8'),
                backend=self.backend
            )
            
            # メモリに保存
            self._active_keys[key_id] = private_key
            
            print(f"  ✓ 秘密鍵の読み込み成功")
            return private_key
            
        except ValueError as e:
            raise CryptoError(f"パスフレーズが正しくないか、鍵ファイルが破損しています: {e}")
    
    def save_public_key(
        self,
        key_id: str,
        public_key: ec.EllipticCurvePublicKey
    ) -> str:
        """
        公開鍵を保存
        
        Args:
            key_id: 鍵の識別子
            public_key: 公開鍵
            
        Returns:
            str: 保存先のファイルパス
        """
        # 公開鍵をPEMフォーマットでシリアライズ
        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        # ファイルに保存
        key_file = self.keys_directory / f"{key_id}_public.pem"
        key_file.write_bytes(pem)
        
        print(f"[KeyManager] 公開鍵を保存: {key_file}")
        
        return str(key_file)
    
    def load_public_key(self, key_id: str) -> ec.EllipticCurvePublicKey:
        """
        公開鍵を読み込み
        
        Args:
            key_id: 鍵の識別子
            
        Returns:
            ec.EllipticCurvePublicKey: 公開鍵
        """
        key_file = self.keys_directory / f"{key_id}_public.pem"
        
        if not key_file.exists():
            raise CryptoError(f"公開鍵ファイルが見つかりません: {key_file}")
        
        pem = key_file.read_bytes()
        public_key = serialization.load_pem_public_key(pem, backend=self.backend)
        
        return public_key
    
    def get_private_key(self, key_id: str) -> Optional[ec.EllipticCurvePrivateKey]:
        """メモリ上の秘密鍵を取得"""
        return self._active_keys.get(key_id)
    
    def public_key_to_base64(self, public_key: ec.EllipticCurvePublicKey) -> str:
        """公開鍵をBase64文字列に変換"""
        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return base64.b64encode(pem).decode('utf-8')
    
    def public_key_from_base64(self, base64_str: str) -> ec.EllipticCurvePublicKey:
        """Base64文字列から公開鍵を復元"""
        pem = base64.b64decode(base64_str.encode('utf-8'))
        return serialization.load_pem_public_key(pem, backend=self.backend)


class SignatureManager:
    """
    署名管理クラス
    データの署名と検証を管理
    """
    
    def __init__(self, key_manager: KeyManager):
        """
        Args:
            key_manager: 鍵管理インスタンス
        """
        self.key_manager = key_manager
        self.backend = default_backend()
    
    def _hash_data(self, data: Any) -> bytes:
        """
        データをハッシュ化
        
        Args:
            data: ハッシュ化するデータ（辞書、文字列など）
            
        Returns:
            bytes: SHA-256ハッシュ
        """
        # データをJSON文字列に変換（決定論的な順序で）
        if isinstance(data, dict):
            json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        elif isinstance(data, str):
            json_str = data
        else:
            json_str = str(data)
        
        # SHA-256でハッシュ化
        return hashlib.sha256(json_str.encode('utf-8')).digest()
    
    def sign_data(
        self,
        data: Any,
        key_id: str,
        algorithm: str = 'ECDSA'
    ) -> Signature:
        """
        データに署名
        
        Args:
            data: 署名するデータ
            key_id: 使用する秘密鍵のID
            algorithm: 署名アルゴリズム（現在はECDSAのみサポート）
            
        Returns:
            Signature: 署名オブジェクト
        """
        print(f"[SignatureManager] データに署名中（鍵ID: {key_id}）")
        
        # 秘密鍵を取得
        private_key = self.key_manager.get_private_key(key_id)
        if private_key is None:
            raise CryptoError(f"秘密鍵が見つかりません: {key_id}")
        
        # データをハッシュ化
        data_hash = self._hash_data(data)
        
        # ECDSA署名
        signature_bytes = private_key.sign(
            data_hash,
            ec.ECDSA(hashes.SHA256())
        )
        
        # 公開鍵を取得
        public_key = private_key.public_key()
        public_key_base64 = self.key_manager.public_key_to_base64(public_key)
        
        # Signatureオブジェクトを作成
        signature = Signature(
            algorithm=algorithm,
            value=base64.b64encode(signature_bytes).decode('utf-8'),
            public_key=public_key_base64,
            signed_at=datetime.utcnow().isoformat() + 'Z'
        )
        
        print(f"  ✓ 署名完了")
        return signature
    
    def verify_signature(
        self,
        data: Any,
        signature: Signature
    ) -> bool:
        """
        署名を検証
        
        Args:
            data: 検証するデータ
            signature: 署名オブジェクト
            
        Returns:
            bool: 検証結果（True=有効、False=無効）
        """
        print(f"[SignatureManager] 署名を検証中...")
        
        try:
            # 公開鍵を復元
            public_key = self.key_manager.public_key_from_base64(signature.public_key)
            
            # データをハッシュ化
            data_hash = self._hash_data(data)
            
            # 署名をデコード
            signature_bytes = base64.b64decode(signature.value.encode('utf-8'))
            
            # ECDSA検証
            public_key.verify(
                signature_bytes,
                data_hash,
                ec.ECDSA(hashes.SHA256())
            )
            
            print(f"  ✓ 署名は有効です")
            return True
            
        except InvalidSignature:
            print(f"  ✗ 署名が無効です")
            return False
        except Exception as e:
            print(f"  ✗ 検証エラー: {e}")
            return False
    
    def sign_mandate(
        self,
        mandate: Dict[str, Any],
        key_id: str
    ) -> Signature:
        """
        Mandateに署名
        
        Args:
            mandate: Mandateの辞書表現
            key_id: 使用する秘密鍵のID
            
        Returns:
            Signature: 署名オブジェクト
        """
        # 署名対象からsignatureフィールドを除外
        mandate_copy = mandate.copy()
        mandate_copy.pop('user_signature', None)
        mandate_copy.pop('merchant_signature', None)
        
        return self.sign_data(mandate_copy, key_id)
    
    def verify_mandate_signature(
        self,
        mandate: Dict[str, Any],
        signature: Signature
    ) -> bool:
        """
        Mandateの署名を検証
        
        Args:
            mandate: Mandateの辞書表現
            signature: 検証する署名
            
        Returns:
            bool: 検証結果
        """
        # 署名対象からsignatureフィールドを除外
        mandate_copy = mandate.copy()
        mandate_copy.pop('user_signature', None)
        mandate_copy.pop('merchant_signature', None)
        
        return self.verify_signature(mandate_copy, signature)


class SecureStorage:
    """
    安全なストレージクラス
    機密データを暗号化して保存
    """
    
    def __init__(self, storage_directory: str = "./secure_storage"):
        """
        Args:
            storage_directory: 暗号化データを保存するディレクトリ
        """
        self.storage_directory = Path(storage_directory)
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self.backend = default_backend()
    
    def _derive_key(self, passphrase: str, salt: bytes) -> bytes:
        """
        パスフレーズから暗号化鍵を導出
        
        Args:
            passphrase: パスフレーズ
            salt: ソルト
            
        Returns:
            bytes: 導出された鍵
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=self.backend
        )
        return kdf.derive(passphrase.encode('utf-8'))
    
    def encrypt_and_save(
        self,
        data: Dict[str, Any],
        filename: str,
        passphrase: str
    ) -> str:
        """
        データを暗号化して保存
        
        Args:
            data: 暗号化するデータ
            filename: ファイル名
            passphrase: パスフレーズ
            
        Returns:
            str: 保存先のファイルパス
        """
        print(f"[SecureStorage] データを暗号化して保存: {filename}")
        
        # データをJSON文字列に変換
        json_data = json.dumps(data, ensure_ascii=False, indent=2)
        plaintext = json_data.encode('utf-8')
        
        # ランダムなソルトとIVを生成
        salt = os.urandom(16)
        iv = os.urandom(16)
        
        # 鍵を導出
        key = self._derive_key(passphrase, salt)
        
        # AES-256-CBCで暗号化
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=self.backend
        )
        encryptor = cipher.encryptor()
        
        # パディング
        padding_length = 16 - (len(plaintext) % 16)
        padded_plaintext = plaintext + bytes([padding_length] * padding_length)
        
        # 暗号化
        ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
        
        # ソルト + IV + 暗号文を結合
        encrypted_data = salt + iv + ciphertext
        
        # ファイルに保存
        file_path = self.storage_directory / filename
        file_path.write_bytes(encrypted_data)
        
        # パーミッションを制限
        os.chmod(file_path, 0o600)
        
        print(f"  ✓ 暗号化して保存完了: {file_path}")
        
        return str(file_path)
    
    def load_and_decrypt(
        self,
        filename: str,
        passphrase: str
    ) -> Dict[str, Any]:
        """
        暗号化されたデータを読み込んで復号化
        
        Args:
            filename: ファイル名
            passphrase: パスフレーズ
            
        Returns:
            Dict[str, Any]: 復号化されたデータ
        """
        print(f"[SecureStorage] データを読み込んで復号化: {filename}")
        
        file_path = self.storage_directory / filename
        
        if not file_path.exists():
            raise CryptoError(f"ファイルが見つかりません: {file_path}")
        
        # ファイルから読み込み
        encrypted_data = file_path.read_bytes()
        
        # ソルト、IV、暗号文を分離
        salt = encrypted_data[:16]
        iv = encrypted_data[16:32]
        ciphertext = encrypted_data[32:]
        
        # 鍵を導出
        key = self._derive_key(passphrase, salt)
        
        # AES-256-CBCで復号化
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=self.backend
        )
        decryptor = cipher.decryptor()
        
        try:
            # 復号化
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            
            # パディングを除去
            padding_length = padded_plaintext[-1]
            plaintext = padded_plaintext[:-padding_length]
            
            # JSONとしてパース
            json_data = plaintext.decode('utf-8')
            data = json.loads(json_data)
            
            print(f"  ✓ 復号化成功")
            return data
            
        except Exception as e:
            raise CryptoError(f"復号化に失敗しました（パスフレーズが正しくない可能性があります）: {e}")


# ========================================
# 使用例
# ========================================

def demo_crypto_operations():
    """暗号操作のデモンストレーション"""
    
    print("=" * 80)
    print("AP2 暗号署名と鍵管理のデモンストレーション")
    print("=" * 80)
    
    # 1. 鍵管理のデモ
    print("\n" + "=" * 80)
    print("1. 鍵ペアの生成と管理")
    print("=" * 80)
    
    key_manager = KeyManager()
    
    # ユーザーの鍵ペアを生成
    user_key_id = "user_123"
    user_private_key, user_public_key = key_manager.generate_key_pair(user_key_id)
    
    # パスフレーズで暗号化して保存
    user_passphrase = "secure_user_passphrase_123"
    key_manager.save_private_key_encrypted(user_key_id, user_private_key, user_passphrase)
    key_manager.save_public_key(user_key_id, user_public_key)
    
    # マーチャントの鍵ペアも生成
    merchant_key_id = "merchant_456"
    merchant_private_key, merchant_public_key = key_manager.generate_key_pair(merchant_key_id)
    merchant_passphrase = "secure_merchant_passphrase_456"
    key_manager.save_private_key_encrypted(merchant_key_id, merchant_private_key, merchant_passphrase)
    key_manager.save_public_key(merchant_key_id, merchant_public_key)
    
    # 2. データへの署名と検証
    print("\n" + "=" * 80)
    print("2. データへの署名と検証")
    print("=" * 80)
    
    signature_manager = SignatureManager(key_manager)
    
    # サンプルデータ
    sample_data = {
        "id": "intent_001",
        "type": "IntentMandate",
        "user_id": "user_123",
        "intent": "新しいランニングシューズを購入したい",
        "max_amount": {"value": "100.00", "currency": "USD"}
    }
    
    print(f"\n署名対象データ:")
    print(json.dumps(sample_data, indent=2, ensure_ascii=False))
    
    # ユーザーが署名
    user_signature = signature_manager.sign_data(sample_data, user_key_id)
    print(f"\n署名値（Base64）: {user_signature.value[:50]}...")
    
    # 署名を検証
    is_valid = signature_manager.verify_signature(sample_data, user_signature)
    print(f"\n署名検証結果: {'✓ 有効' if is_valid else '✗ 無効'}")
    
    # 改ざんされたデータで検証
    tampered_data = sample_data.copy()
    tampered_data["max_amount"]["value"] = "1000.00"  # 金額を改ざん
    
    print(f"\n改ざんされたデータで検証:")
    is_valid_tampered = signature_manager.verify_signature(tampered_data, user_signature)
    print(f"検証結果: {'✓ 有効' if is_valid_tampered else '✗ 無効（期待通り）'}")
    
    # 3. 秘密鍵の読み込み
    print("\n" + "=" * 80)
    print("3. 秘密鍵の読み込みと再利用")
    print("=" * 80)
    
    # 新しいKeyManagerインスタンスで鍵を読み込み
    new_key_manager = KeyManager()
    loaded_private_key = new_key_manager.load_private_key_encrypted(
        user_key_id,
        user_passphrase
    )
    
    # 読み込んだ鍵で署名
    new_signature_manager = SignatureManager(new_key_manager)
    new_signature = new_signature_manager.sign_data(sample_data, user_key_id)
    
    # 新しい署名を元の公開鍵で検証
    is_valid_new = signature_manager.verify_signature(sample_data, new_signature)
    print(f"読み込んだ鍵での署名検証: {'✓ 有効' if is_valid_new else '✗ 無効'}")
    
    # 4. 機密データの暗号化保存
    print("\n" + "=" * 80)
    print("4. 機密データの暗号化保存")
    print("=" * 80)
    
    secure_storage = SecureStorage()
    
    # 機密データ（例：支払い情報）
    sensitive_data = {
        "user_id": "user_123",
        "payment_methods": [
            {
                "type": "card",
                "token": "tok_secret_12345",
                "last4": "4242",
                "brand": "visa"
            }
        ],
        "shipping_address": {
            "street": "123 Main St",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105"
        }
    }
    
    storage_passphrase = "storage_passphrase_789"
    secure_storage.encrypt_and_save(
        sensitive_data,
        "user_123_data.enc",
        storage_passphrase
    )
    
    # 暗号化データを読み込み
    decrypted_data = secure_storage.load_and_decrypt(
        "user_123_data.enc",
        storage_passphrase
    )
    
    print(f"\n復号化されたデータ:")
    print(json.dumps(decrypted_data, indent=2, ensure_ascii=False))
    
    print("\n" + "=" * 80)
    print("デモンストレーション完了!")
    print("=" * 80)
    print("\n生成されたファイル:")
    print("  - ./keys/user_123_private.pem (暗号化された秘密鍵)")
    print("  - ./keys/user_123_public.pem (公開鍵)")
    print("  - ./keys/merchant_456_private.pem (暗号化された秘密鍵)")
    print("  - ./keys/merchant_456_public.pem (公開鍵)")
    print("  - ./secure_storage/user_123_data.enc (暗号化されたデータ)")


if __name__ == "__main__":
    demo_crypto_operations()
