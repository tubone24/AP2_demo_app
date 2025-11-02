"""
v2/common/auth.py

メール/パスワード認証 + JWT統合モジュール（AP2仕様準拠）

AP2アーキテクチャ:
- HTTPセッション認証: メール/パスワード → JWT（AP2仕様外、実装の自由度あり）
- Mandate署名: WebAuthn/Passkey（Credential Provider）← AP2仕様準拠

リファレンス実装との対応:
- email = payer_email（例: bugsbunny@gmail.com）
- パスワード認証後、JWTを発行してセッション管理
- bcryptでパスワードをハッシュ化
"""

import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta

import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

try:
    from common.models import TokenData, UserInDB
    from common.database import DatabaseManager, UserCRUD
    from common.logger import get_logger
except ModuleNotFoundError:
    from common.models import TokenData, UserInDB
    from common.database import DatabaseManager, UserCRUD
    from common.logger import get_logger

logger = get_logger(__name__, service_name='auth')

# JWT設定（環境変数から取得）
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "INSECURE_DEFAULT_KEY_CHANGE_IN_PRODUCTION")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24時間

if SECRET_KEY == "INSECURE_DEFAULT_KEY_CHANGE_IN_PRODUCTION":
    logger.warning(
        "[Auth] Using default JWT_SECRET_KEY. "
        "SECURITY RISK: Set JWT_SECRET_KEY environment variable in production!"
    )

# FastAPI HTTPBearer設定
security = HTTPBearer()

# パスワードハッシュ化設定（2025年ベストプラクティス）
# Argon2id: メモリハード関数、サイドチャネル攻撃耐性あり
# OWASP推奨パラメータ: time_cost=2, memory_cost=19456 (19 MiB), parallelism=1
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__time_cost=2,
    argon2__memory_cost=19456,  # 19 MiB
    argon2__parallelism=1,
    argon2__type="id",  # Argon2id（ハイブリッド型）
)


# ========================================
# パスワード認証（Argon2id - 2025年ベストプラクティス）
# ========================================

def validate_password_strength(password: str) -> bool:
    """
    パスワード強度を検証

    OWASP推奨基準:
    - 最低8文字
    - 大文字・小文字・数字を含む
    - 一般的な辞書単語を避ける

    Args:
        password: 検証するパスワード

    Returns:
        bool: 強度が十分な場合True

    Raises:
        HTTPException: パスワードが弱い場合
    """
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)

    if not (has_upper and has_lower and has_digit):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain uppercase, lowercase, and digits"
        )

    # 一般的な弱いパスワードチェック
    weak_passwords = ["password", "12345678", "qwerty", "admin", "letmein"]
    if password.lower() in weak_passwords:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is too weak. Please choose a stronger password"
        )

    return True


def hash_password(password: str) -> str:
    """
    パスワードをArgon2idでハッシュ化

    Argon2id特徴:
    - メモリハード関数（GPU攻撃耐性）
    - サイドチャネル攻撃耐性
    - 2015 Password Hashing Competition優勝
    - OWASP推奨アルゴリズム

    Args:
        password: 平文パスワード

    Returns:
        str: Argon2idハッシュ（$argon2id$...形式）
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    パスワードを検証

    タイミング攻撃耐性あり（constant-time comparison）

    Args:
        plain_password: 平文パスワード
        hashed_password: Argon2idハッシュ

    Returns:
        bool: パスワードが一致する場合True
    """
    return pwd_context.verify(plain_password, hashed_password)


# ========================================
# JWT トークン処理
# ========================================

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    JWTアクセストークンを作成

    Args:
        data: トークンに含めるデータ（user_id, emailなど）
        expires_delta: 有効期限（デフォルト: ACCESS_TOKEN_EXPIRE_MINUTES）

    Returns:
        str: JWTトークン
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})

    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    logger.info(f"[Auth] Created JWT token: user_id={data.get('user_id')}, expires={expire.isoformat()}")

    return encoded_jwt


def verify_access_token(token: str) -> TokenData:
    """
    JWTアクセストークンを検証してペイロードを取得

    Args:
        token: JWTトークン

    Returns:
        TokenData: トークンのペイロードデータ

    Raises:
        HTTPException: トークンが無効または期限切れの場合
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("user_id")
        email: str = payload.get("email")

        if user_id is None:
            raise credentials_exception

        token_data = TokenData(user_id=user_id, email=email)
        return token_data

    except jwt.ExpiredSignatureError:
        logger.warning("[Auth] JWT token expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.error(f"[Auth] Invalid JWT token: {e}")
        raise credentials_exception


# ========================================
# FastAPI 依存性（Dependency Injection）
# ========================================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db_manager: DatabaseManager = None  # Shopping Agentから注入される
) -> UserInDB:
    """
    現在のユーザーを取得（FastAPI Dependency）

    HTTPリクエストのAuthorizationヘッダーからJWTを抽出し、
    ユーザー情報をデータベースから取得

    Args:
        credentials: HTTPBearer認証情報
        db_manager: データベースマネージャー（依存性注入）

    Returns:
        UserInDB: 現在のユーザー情報

    Raises:
        HTTPException: 認証失敗時

    使用例:
        @app.get("/protected")
        async def protected_route(current_user: UserInDB = Depends(get_current_user)):
            return {"user_id": current_user.id, "email": current_user.email}
    """
    token = credentials.credentials
    token_data = verify_access_token(token)

    if not db_manager:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database manager not configured"
        )

    async with db_manager.get_session() as session:
        user = await UserCRUD.get_by_id(session, token_data.user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )

    # UserInDB Pydanticモデルに変換（AP2完全準拠）
    user_in_db = UserInDB(
        id=user.id,
        username=user.display_name,
        email=user.email,
        hashed_password=user.hashed_password,  # AP2準拠: Argon2idハッシュ
        created_at=user.created_at,
        is_active=bool(user.is_active)
    )

    logger.debug(f"[Auth] Authenticated user: {user.email}")

    return user_in_db


# ========================================
# WebAuthn/Passkey 検証
# ========================================
# 注意: WebAuthn検証は Credential Provider が実施
# Shopping Agent では Layer 2 認証としてのみ使用


# ========================================
# エクスポート
# ========================================

__all__ = [
    "create_access_token",
    "verify_access_token",
    "get_current_user",
    "SECRET_KEY",
    "ALGORITHM",
]
