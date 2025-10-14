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

from ap2_types import Signature, DeviceAttestation, AttestationType


class CryptoError(Exception):
    """暗号処理に関するエラー"""
    pass


# ========================================
# Mandate Hash計算ユーティリティ
# ========================================

def compute_mandate_hash(
    mandate: Dict[str, Any],
    hash_format: str = 'hex'
) -> str:
    """
    MandateのCanonical JSONからSHA-256ハッシュを計算

    AP2仕様では、Mandateの整合性検証のために
    canonicalized JSON（正規化されたJSON）のハッシュを使用する。

    Args:
        mandate: Mandateの辞書表現
        hash_format: ハッシュの出力形式 ('hex' or 'base64')

    Returns:
        str: SHA-256ハッシュ（hex形式またはbase64形式）
    """
    # 1. 署名フィールドを除外（署名前の状態でハッシュ化）
    mandate_copy = mandate.copy()
    mandate_copy.pop('user_signature', None)
    mandate_copy.pop('merchant_signature', None)
    mandate_copy.pop('mandate_metadata', None)  # メタデータも除外（ハッシュ自体を含むため）

    # 2. Enumを.valueに変換
    def convert_enums(data: Any) -> Any:
        if isinstance(data, dict):
            return {key: convert_enums(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [convert_enums(item) for item in data]
        elif hasattr(data, 'value'):  # Enumの場合
            return data.value
        else:
            return data

    converted_mandate = convert_enums(mandate_copy)

    # 3. Canonical JSON文字列を生成
    # - キーをアルファベット順にソート
    # - 余分なスペースを削除
    # - UTF-8エンコーディング
    canonical_json = json.dumps(
        converted_mandate,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False
    )

    # 4. SHA-256ハッシュを計算
    hash_bytes = hashlib.sha256(canonical_json.encode('utf-8')).digest()

    # 5. 指定された形式で返す
    if hash_format == 'base64':
        return base64.b64encode(hash_bytes).decode('utf-8')
    elif hash_format == 'hex':
        return hash_bytes.hex()
    else:
        raise ValueError(f"Unsupported hash format: {hash_format}. Use 'hex' or 'base64'.")


def verify_mandate_hash(
    mandate: Dict[str, Any],
    expected_hash: str,
    hash_format: str = 'hex'
) -> bool:
    """
    Mandateのハッシュを検証

    Args:
        mandate: 検証するMandateの辞書表現
        expected_hash: 期待されるハッシュ値
        hash_format: ハッシュの形式 ('hex' or 'base64')

    Returns:
        bool: ハッシュが一致する場合True
    """
    actual_hash = compute_mandate_hash(mandate, hash_format)
    return actual_hash == expected_hash


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
    
    def _convert_enums(self, data: Any) -> Any:
        """
        データ内のEnumを再帰的に.valueに変換

        Args:
            data: 変換するデータ

        Returns:
            Enumが変換されたデータ
        """
        if isinstance(data, dict):
            return {key: self._convert_enums(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._convert_enums(item) for item in data]
        elif hasattr(data, 'value'):  # Enumの場合
            return data.value
        else:
            return data

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
            # Enumを.valueに変換
            converted_data = self._convert_enums(data)
            json_str = json.dumps(converted_data, sort_keys=True, ensure_ascii=False)
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
        # Intent Mandateの場合は、intentとconstraintsフィールドのみを署名対象にする
        if mandate.get('type') == 'IntentMandate':
            # intentとconstraintsのみを署名対象にする
            signing_data = {
                'intent': mandate.get('intent'),
                'constraints': mandate.get('constraints')
            }
            return self.sign_data(signing_data, key_id)

        # 他のMandateタイプの場合は、署名対象からsignatureフィールドを除外
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
        # Intent Mandateの場合は、intentとconstraintsフィールドのみを検証対象にする
        if mandate.get('type') == 'IntentMandate':
            # intentとconstraintsのみを検証対象にする
            verification_data = {
                'intent': mandate.get('intent'),
                'constraints': mandate.get('constraints')
            }
            return self.verify_signature(verification_data, signature)

        # 他のMandateタイプの場合は、署名対象からsignatureフィールドを除外
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


class DeviceAttestationManager:
    """
    Device Attestation管理クラス

    AP2ステップ20-23で使用される、デバイス証明の生成と検証を管理。
    ユーザーのデバイスが信頼されており、取引が改ざんされていないことを保証する。
    """

    def __init__(self, key_manager: KeyManager):
        """
        Args:
            key_manager: 鍵管理インスタンス
        """
        self.key_manager = key_manager
        self.backend = default_backend()

    def generate_challenge(self) -> str:
        """
        チャレンジ値を生成（リプレイ攻撃対策）

        Returns:
            str: ランダムなチャレンジ値（Base64）
        """
        challenge_bytes = os.urandom(32)  # 256ビット
        return base64.b64encode(challenge_bytes).decode('utf-8')

    def verify_webauthn_signature_simplified(
        self,
        webauthn_auth_result: Dict[str, Any],
        challenge: str,
        rp_id: str = "localhost"
    ) -> bool:
        """
        WebAuthn認証結果の簡易検証

        注意: これは教育デモ用の簡易実装です。
        本番環境では以下の完全な検証が必要です：
        - Passkey登録時の公開鍵保存
        - credential_id → public_key のマッピング
        - CBOR形式のauthenticatorDataパース
        - 暗号学的な署名検証（公開鍵による）

        現在の実装では以下のみをチェックします：
        - clientDataJSONのchallenge検証
        - タイムスタンプの鮮度
        - 署名データの存在確認

        Args:
            webauthn_auth_result: WebAuthn認証結果のJSON
            challenge: サーバーが発行したchallenge（Base64）
            rp_id: Relying Party ID

        Returns:
            bool: 基本検証をパスした場合True
        """
        print(f"[DeviceAttestationManager] WebAuthn認証結果を簡易検証中...")

        try:
            # 1. 成功フラグの確認
            if not webauthn_auth_result.get('success'):
                print(f"  ✗ 認証が成功していません")
                return False

            # 2. clientDataJSONをデコードしてパース
            client_data_json_b64 = webauthn_auth_result.get('clientDataJSON')
            if not client_data_json_b64:
                print(f"  ✗ clientDataJSONがありません")
                return False

            # WebAuthnはBase64URLを使用するため、パディングを追加してデコード
            # パディングが不足している場合に備えて追加
            padding_needed = len(client_data_json_b64) % 4
            if padding_needed:
                client_data_json_b64 += '=' * (4 - padding_needed)

            try:
                # Base64URLデコードを試みる
                client_data_json = base64.urlsafe_b64decode(client_data_json_b64)
            except Exception as e:
                print(f"  ✗ clientDataJSONのデコードに失敗: {e}")
                return False

            client_data = json.loads(client_data_json)

            print(f"  - Client Data Type: {client_data.get('type')}")
            print(f"  - Origin: {client_data.get('origin')}")

            # 3. Challenge検証（リプレイ攻撃対策）
            received_challenge = client_data.get('challenge')
            if not received_challenge:
                print(f"  ✗ clientDataJSONにchallengeがありません")
                return False

            # challengeを正規化（Base64URL → Base64への変換を考慮）
            # WebAuthnはBase64URLを使用するが、比較のため正規化
            if received_challenge != challenge:
                print(f"  ✗ Challenge不一致")
                print(f"    期待値: {challenge[:20]}...")
                print(f"    受信値: {received_challenge[:20]}...")
                return False

            print(f"  ✓ Challenge一致: {challenge[:20]}...")

            # 4. タイプ検証
            if client_data.get('type') != 'webauthn.get':
                print(f"  ✗ 認証タイプが正しくありません: {client_data.get('type')}")
                return False

            print(f"  ✓ 認証タイプ: webauthn.get")

            # 5. 署名データの存在確認
            signature = webauthn_auth_result.get('signature')
            if not signature:
                print(f"  ✗ 署名データがありません")
                return False

            authenticator_data = webauthn_auth_result.get('authenticatorData')
            if not authenticator_data:
                print(f"  ✗ authenticatorDataがありません")
                return False

            print(f"  ✓ 署名データ存在確認: {len(signature)} chars")
            print(f"  ✓ AuthenticatorData存在確認: {len(authenticator_data)} chars")

            # 6. タイムスタンプの鮮度チェック
            timestamp_ms = webauthn_auth_result.get('timestamp')
            if timestamp_ms:
                # time.time()を使用してUTC時刻を取得（タイムゾーンの問題を回避）
                import time
                current_time_ms = time.time() * 1000

                age_ms = abs(current_time_ms - timestamp_ms)
                age_seconds = age_ms / 1000
                max_age_seconds = 300  # 5分

                if age_seconds > max_age_seconds:
                    print(f"  ✗ タイムスタンプが古すぎます: {age_seconds:.0f}秒前")
                    return False

                print(f"  ✓ タイムスタンプの鮮度: {age_seconds:.0f}秒前（最大{max_age_seconds}秒）")

            print(f"  ✓ WebAuthn基本検証をパスしました")
            print(f"  ⚠️  注意: 公開鍵による暗号学的な署名検証は未実装")
            print(f"       本番環境では完全な検証が必要です")

            return True

        except json.JSONDecodeError as e:
            print(f"  ✗ clientDataJSONのパースに失敗: {e}")
            return False
        except Exception as e:
            print(f"  ✗ WebAuthn検証エラー: {e}")
            return False

    def create_device_attestation(
        self,
        device_id: str,
        payment_mandate: 'PaymentMandate',
        device_key_id: str,
        attestation_type: AttestationType = AttestationType.BIOMETRIC,
        platform: str = "iOS",
        os_version: Optional[str] = None,
        app_version: Optional[str] = None,
        timestamp: Optional[str] = None,
        challenge: Optional[str] = None,
        webauthn_signature: Optional[str] = None,
        webauthn_authenticator_data: Optional[str] = None,
        webauthn_client_data_json: Optional[str] = None
    ) -> DeviceAttestation:
        """
        デバイス証明を作成

        AP2ステップ21に対応：ユーザーがデバイスで取引を承認し、
        デバイスが暗号学的証明を生成する。

        Args:
            device_id: デバイスの一意識別子
            payment_mandate: 署名するPayment Mandate
            device_key_id: デバイスの秘密鍵ID
            attestation_type: 認証タイプ
            platform: プラットフォーム（"iOS", "Android", "Web"など）
            os_version: OSバージョン
            app_version: アプリバージョン
            timestamp: タイムスタンプ（ISO 8601形式、Noneの場合は現在時刻）
            challenge: チャレンジ値（Noneの場合は自動生成）
            webauthn_signature: WebAuthn署名データ（オプション）
            webauthn_authenticator_data: WebAuthn Authenticator Data（オプション）
            webauthn_client_data_json: WebAuthn Client Data JSON（オプション）

        Returns:
            DeviceAttestation: デバイス証明
        """
        print(f"[DeviceAttestationManager] デバイス証明を作成中...")
        print(f"  デバイスID: {device_id}")
        print(f"  認証タイプ: {attestation_type.value}")
        print(f"  プラットフォーム: {platform}")

        # チャレンジ値を生成（または指定されたものを使用）
        if challenge is None:
            challenge = self.generate_challenge()

        # デバイスの秘密鍵を取得
        device_private_key = self.key_manager.get_private_key(device_key_id)
        if device_private_key is None:
            raise CryptoError(f"デバイス秘密鍵が見つかりません: {device_key_id}")

        device_public_key = device_private_key.public_key()
        device_public_key_base64 = self.key_manager.public_key_to_base64(device_public_key)

        # タイムスタンプを設定（指定されたものを使用、またはデフォルトで現在時刻）
        if timestamp is None:
            timestamp = datetime.utcnow().isoformat() + 'Z'
            print(f"  タイムスタンプを生成: {timestamp}")
        else:
            print(f"  指定されたタイムスタンプを使用: {timestamp}")
        attestation_data = {
            "device_id": device_id,
            "payment_mandate_id": payment_mandate.id,
            "challenge": challenge,
            "timestamp": timestamp,
            "attestation_type": attestation_type.value,
            "platform": platform
        }

        # データをJSON文字列に変換してハッシュ化
        json_str = json.dumps(attestation_data, sort_keys=True, ensure_ascii=False)
        data_hash = hashlib.sha256(json_str.encode('utf-8')).digest()

        # ECDSA署名を生成
        attestation_signature = device_private_key.sign(
            data_hash,
            ec.ECDSA(hashes.SHA256())
        )
        attestation_value = base64.b64encode(attestation_signature).decode('utf-8')

        # DeviceAttestationオブジェクトを作成
        device_attestation = DeviceAttestation(
            device_id=device_id,
            attestation_type=attestation_type,
            attestation_value=attestation_value,
            timestamp=timestamp,
            device_public_key=device_public_key_base64,
            challenge=challenge,
            platform=platform,
            os_version=os_version,
            app_version=app_version
        )

        print(f"  ✓ デバイス証明を作成完了")
        print(f"  チャレンジ: {challenge[:16]}...")
        print(f"  タイムスタンプ: {timestamp}")

        return device_attestation

    def verify_device_attestation(
        self,
        device_attestation: DeviceAttestation,
        payment_mandate: 'PaymentMandate',
        max_age_seconds: int = 300
    ) -> bool:
        """
        デバイス証明を検証

        AP2ステップ26でCredential Providerが実行する検証。

        Args:
            device_attestation: 検証するデバイス証明
            payment_mandate: 対応するPayment Mandate
            max_age_seconds: 証明の最大有効期間（秒）

        Returns:
            bool: 検証結果（True=有効、False=無効）
        """
        print(f"[DeviceAttestationManager] デバイス証明を検証中...")
        print(f"  デバイスID: {device_attestation.device_id}")
        print(f"  認証タイプ: {device_attestation.attestation_type.value}")

        try:
            # 1. タイムスタンプを確認（リプレイ攻撃対策）
            attestation_time = datetime.fromisoformat(device_attestation.timestamp.replace('Z', '+00:00'))
            now = datetime.utcnow()
            age_seconds = (now - attestation_time.replace(tzinfo=None)).total_seconds()

            # 未来のタイムスタンプを拒否（リプレイ攻撃対策）
            if age_seconds < 0:
                print(f"  ✗ 証明のタイムスタンプが未来です（{abs(age_seconds):.0f}秒後）")
                print(f"    - Device Attestation: {device_attestation.timestamp}")
                print(f"    - 現在時刻: {now.isoformat()}Z")
                return False

            # タイムスタンプが古すぎる場合を拒否
            if age_seconds > max_age_seconds:
                print(f"  ✗ 証明が古すぎます（{age_seconds:.0f}秒前、最大{max_age_seconds}秒）")
                print(f"    - Device Attestation: {device_attestation.timestamp}")
                print(f"    - 現在時刻: {now.isoformat()}Z")
                return False

            print(f"  ✓ タイムスタンプは有効（{age_seconds:.0f}秒前、最大{max_age_seconds}秒）")

            # 2. Payment Mandate IDが一致するか確認
            # 署名対象データを再構築
            attestation_data = {
                "device_id": device_attestation.device_id,
                "payment_mandate_id": payment_mandate.id,
                "challenge": device_attestation.challenge,
                "timestamp": device_attestation.timestamp,
                "attestation_type": device_attestation.attestation_type.value,
                "platform": device_attestation.platform
            }

            # データをJSON文字列に変換してハッシュ化
            json_str = json.dumps(attestation_data, sort_keys=True, ensure_ascii=False)
            data_hash = hashlib.sha256(json_str.encode('utf-8')).digest()

            # 3. デバイスの公開鍵で署名を検証
            device_public_key = self.key_manager.public_key_from_base64(
                device_attestation.device_public_key
            )
            attestation_signature = base64.b64decode(device_attestation.attestation_value.encode('utf-8'))

            device_public_key.verify(
                attestation_signature,
                data_hash,
                ec.ECDSA(hashes.SHA256())
            )

            print(f"  ✓ デバイス証明は有効です")
            return True

        except InvalidSignature:
            print(f"  ✗ デバイス署名が無効です")
            return False
        except Exception as e:
            print(f"  ✗ 検証エラー: {e}")
            return False


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
