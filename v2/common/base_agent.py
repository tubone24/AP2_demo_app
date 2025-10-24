"""
v2/common/base_agent.py

全エージェントの基底クラス
共通のPOST /a2a/messageエンドポイントと初期化ロジックを提供
"""

import sys
import os
from abc import ABC, abstractmethod
from typing import Dict, Any
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# v2の暗号化モジュールをインポート
from common.crypto import KeyManager, SignatureManager

from .models import A2AMessage
from .a2a_handler import A2AMessageHandler

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    全エージェントの基底クラス

    demo_app_v2.mdの要件：
    - 各エージェントは独立したFastAPIサービス
    - 共通エンドポイント: POST /a2a/message
    - A2Aメッセージの受信→署名検証→処理→署名付きレスポンス
    """

    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        passphrase: str,
        keys_directory: str = "./keys"
    ):
        """
        Args:
            agent_id: エージェントDID (e.g., "did:ap2:agent:shopping_agent")
            agent_name: エージェント名 (e.g., "Shopping Agent")
            passphrase: 秘密鍵のパスフレーズ
            keys_directory: 鍵保存ディレクトリ
        """
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.passphrase = passphrase

        # FastAPIアプリ
        self.app = FastAPI(
            title=agent_name,
            description=f"AP2 Protocol {agent_name} Service",
            version="2.0.0"
        )

        # CORS設定
        self._setup_cors()

        # 環境変数からkeys_directoryを取得（Docker環境対応）
        import os
        keys_dir = os.getenv("AP2_KEYS_DIRECTORY", keys_directory)

        # 鍵管理と署名管理の初期化
        self.key_manager = KeyManager(keys_directory=keys_dir)
        self.signature_manager = SignatureManager(self.key_manager)

        # 鍵の読み込みまたは生成
        self._init_keys()

        # A2Aメッセージハンドラー
        self.a2a_handler = A2AMessageHandler(
            agent_id=agent_id,
            key_manager=self.key_manager,
            signature_manager=self.signature_manager
        )

        # サブクラスでハンドラーを登録
        self.register_a2a_handlers()

        # 共通エンドポイントを登録
        self._register_common_endpoints()

        # サブクラス固有のエンドポイントを登録
        self.register_endpoints()

        logger.info(f"[{self.agent_name}] Initialized: {self.agent_id}")

    def _setup_cors(self):
        """CORS設定"""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:3000",
                "http://localhost:8000",
                "http://localhost:8001",
                "http://localhost:8002",
                "http://localhost:8003",
                "http://localhost:8004",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _init_keys(self):
        """
        鍵の初期化（永続化ストレージから読み込み）

        セキュリティ要件（専門家の指摘対応）：
        - キーペアはv2/scripts/init_keys.pyで事前に生成・暗号化されている
        - 各エージェントは永続化ストレージ（Docker Volume）から既存の鍵を読み込む
        - DIDドキュメントも永続化されているため、DIDは再起動後も一貫している
        - 開発時の利便性のため、鍵が存在しない場合は自動生成（本番環境では非推奨）
        """
        # agent_idから鍵IDを抽出（例: did:ap2:agent:shopping_agent -> shopping_agent）
        key_id = self.agent_id.split(":")[-1]

        try:
            # 永続化ストレージから既存のECDSA鍵を読み込み（JWT署名用）
            self.key_manager.load_private_key_encrypted(key_id, self.passphrase, algorithm="ECDSA")
            logger.info(
                f"[{self.agent_name}] ✓ ECDSA鍵を読み込みました: {key_id}"
            )
        except Exception as e:
            # 鍵が存在しない場合はエラー
            logger.error(
                f"[{self.agent_name}] ❌ ECDSA鍵が見つかりません。\n"
                f"   鍵を生成するには以下のコマンドを実行してください:\n"
                f"   \n"
                f"   cd /app/v2 && python scripts/init_keys.py\n"
                f"   \n"
                f"   または Docker環境では:\n"
                f"   \n"
                f"   docker compose exec {self.agent_name.lower().replace(' ', '_')} python /app/v2/scripts/init_keys.py\n"
                f"   \n"
                f"   Error: {e}"
            )
            raise RuntimeError(
                f"ECDSA鍵が見つかりません。v2/scripts/init_keys.py を実行してください。"
            ) from e

        # Ed25519鍵を読み込み（A2A通信用）
        try:
            self.key_manager.load_private_key_encrypted(key_id, self.passphrase, algorithm="ED25519")
            logger.info(
                f"[{self.agent_name}] ✓ Ed25519鍵を読み込みました: {key_id}"
            )
        except Exception as e:
            # Ed25519鍵が存在しない場合はエラー
            logger.error(
                f"[{self.agent_name}] ❌ Ed25519鍵が見つかりません。\n"
                f"   鍵を生成するには以下のコマンドを実行してください:\n"
                f"   \n"
                f"   cd /app/v2 && python scripts/init_keys.py\n"
                f"   \n"
                f"   または Docker環境では:\n"
                f"   \n"
                f"   docker compose exec {self.agent_name.lower().replace(' ', '_')} python /app/v2/scripts/init_keys.py\n"
                f"   \n"
                f"   Error: {e}"
            )
            raise RuntimeError(
                f"Ed25519鍵が見つかりません。v2/scripts/init_keys.py を実行してください。"
            ) from e

    def _register_common_endpoints(self):
        """共通エンドポイントの登録"""

        @self.app.get("/")
        async def root():
            """ヘルスチェック"""
            return {
                "agent_id": self.agent_id,
                "agent_name": self.agent_name,
                "status": "running",
                "version": "2.0.0"
            }

        @self.app.post("/a2a/message")
        async def handle_a2a_message(message: A2AMessage):
            """
            POST /a2a/message - 共通A2Aメッセージエンドポイント

            demo_app_v2.md:
            - A2AMessageを受信
            - 署名検証
            - dataPart["@type"]に基づいてディスパッチ
            - ビジネスロジック実行
            - 署名付きレスポンスを返却
            """
            try:
                logger.info(
                    f"\n{'='*80}\n"
                    f"[{self.agent_name}] A2Aエンドポイント: POST /a2a/message\n"
                    f"  受信メッセージ: ID={message.header.message_id}\n"
                    f"  送信元: {message.header.sender}\n"
                    f"  タイプ: {message.dataPart.type}\n"
                    f"{'='*80}"
                )

                # メッセージ処理（署名検証＋ハンドラー呼び出し）
                result = await self.a2a_handler.handle_message(message)

                # Artifactレスポンスの場合（AP2/A2A仕様準拠）
                if result.get("is_artifact"):
                    response = self.a2a_handler.create_artifact_response(
                        recipient=message.header.sender,
                        artifact_name=result.get("artifact_name", "Artifact"),
                        artifact_data=result.get("artifact_data", {}),
                        data_type_key=result.get("data_type_key", "data"),
                        sign=True
                    )
                # 通常のメッセージレスポンス
                else:
                    response = self.a2a_handler.create_response_message(
                        recipient=message.header.sender,
                        data_type=result.get("type", "ap2/Response"),
                        data_id=result.get("id", message.dataPart.id),
                        payload=result.get("payload", {}),
                        sign=True
                    )

                logger.info(
                    f"[{self.agent_name}] A2Aレスポンス返却: "
                    f"type={result.get('type')}, to={message.header.sender}"
                )

                return response

            except ValueError as e:
                logger.error(
                    f"[{self.agent_name}] Validation error in A2A message: {e}\n"
                    f"  Message ID: {message.header.message_id}\n"
                    f"  Sender: {message.header.sender}"
                )
                error_response = self.a2a_handler.create_error_response(
                    recipient=message.header.sender,
                    error_code="invalid_request",
                    error_message=str(e)
                )
                raise HTTPException(status_code=400, detail=error_response.model_dump())

            except Exception as e:
                logger.error(
                    f"[{self.agent_name}] Internal error in A2A message: {e}\n"
                    f"  Message ID: {message.header.message_id}\n"
                    f"  Sender: {message.header.sender}",
                    exc_info=True
                )
                error_response = self.a2a_handler.create_error_response(
                    recipient=message.header.sender,
                    error_code="internal_error",
                    error_message="Internal server error"
                )
                raise HTTPException(status_code=500, detail=error_response.model_dump())

        @self.app.get("/health")
        async def health_check():
            """ヘルスチェック（Docker向け）"""
            return {"status": "healthy"}

        @self.app.get("/.well-known/agent-card.json")
        async def get_agent_card():
            """
            GET /.well-known/agent-card.json - AgentCard取得

            AP2/A2A仕様準拠：a2a-extension.md
            各エージェントはAP2拡張をサポートすることを宣言する
            """
            try:
                # サブクラスから情報を取得
                ap2_roles = self.get_ap2_roles()
                description = self.get_agent_description()

                # AgentCard構造（A2A標準 + AP2拡張）
                agent_card = {
                    "name": self.agent_name,
                    "description": description,
                    "capabilities": {
                        "extensions": [
                            {
                                "uri": "https://github.com/google-agentic-commerce/ap2/tree/v0.1",
                                "description": "This agent supports the Agent Payments Protocol (AP2)",
                                "params": {
                                    "roles": ap2_roles
                                }
                            }
                        ]
                    }
                }

                logger.info(f"[{self.agent_name}] Serving AgentCard: roles={ap2_roles}")
                return agent_card

            except Exception as e:
                logger.error(f"[{self.agent_name}] Error generating AgentCard: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to generate AgentCard")

    @abstractmethod
    def register_a2a_handlers(self):
        """
        サブクラスでオーバーライド：A2Aハンドラーの登録

        例：
        self.a2a_handler.register_handler("ap2/IntentMandate", self.handle_intent_mandate)
        """
        pass

    @abstractmethod
    def register_endpoints(self):
        """
        サブクラスでオーバーライド：固有エンドポイントの登録

        例：
        @self.app.post("/chat/stream")
        async def chat_stream(...):
            ...
        """
        pass

    @abstractmethod
    def get_ap2_roles(self) -> list[str]:
        """
        サブクラスでオーバーライド：AP2でのロールを返す

        Returns:
            list[str]: AP2ロールのリスト
                       ["merchant", "shopper", "credentials-provider", "payment-processor"]
        """
        pass

    @abstractmethod
    def get_agent_description(self) -> str:
        """
        サブクラスでオーバーライド：エージェントの説明を返す

        Returns:
            str: エージェントの説明文
        """
        pass


class AgentPassphraseManager:
    """
    エージェントのパスフレーズを管理

    セキュリティ要件（専門家の指摘対応）：
    - ハードコードされたデフォルトパスフレーズは使用しない
    - 環境変数からのみパスフレーズを取得
    - fail-closed security: 環境変数が未設定の場合はエラー
    """

    @staticmethod
    def get_passphrase(agent_key: str) -> str:
        """
        エージェントのパスフレーズを取得

        Args:
            agent_key: エージェントキー (e.g., "shopping_agent")

        Returns:
            str: パスフレーズ

        Raises:
            RuntimeError: 環境変数が設定されていない場合
        """
        import os

        # 環境変数から取得（必須）
        env_key = f"AP2_{agent_key.upper()}_PASSPHRASE"
        passphrase = os.getenv(env_key)

        if not passphrase:
            raise RuntimeError(
                f"❌ セキュリティエラー: 環境変数 {env_key} が設定されていません。\n"
                f"   セキュリティのため、パスフレーズは環境変数での設定が必須です。\n"
                f"   .env.exampleを参照して、.envファイルに設定してください。"
            )

        return passphrase
