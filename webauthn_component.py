"""
WebAuthn Component for Streamlit
ブラウザのWeb Authentication API（Passkey）を使った実際の認証
"""

import streamlit as st
import streamlit.components.v1 as components
import json
import base64
import secrets


def webauthn_authenticate(challenge: str, rp_id: str = "localhost", user_id: str = "demo_user"):
    """
    WebAuthn（Passkey）を使った認証を実行

    Args:
        challenge: サーバーから発行されたチャレンジ（Base64エンコード済み）
        rp_id: Relying Party ID（通常はドメイン名）
        user_id: ユーザーID

    Returns:
        認証結果（署名データ、authenticatorDataなど）
    """

    # WebAuthn JavaScriptコンポーネント
    webauthn_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 20px;
                background: #f8f9fa;
                border-radius: 10px;
            }}
            .status {{
                padding: 15px;
                margin: 10px 0;
                border-radius: 8px;
                font-size: 14px;
            }}
            .status.info {{
                background: #e3f2fd;
                border-left: 4px solid #2196f3;
                color: #1565c0;
            }}
            .status.success {{
                background: #e8f5e9;
                border-left: 4px solid #4caf50;
                color: #2e7d32;
            }}
            .status.error {{
                background: #ffebee;
                border-left: 4px solid #f44336;
                color: #c62828;
            }}
            button {{
                background: #2196f3;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
                margin: 10px 0;
            }}
            button:hover {{
                background: #1976d2;
            }}
            button:disabled {{
                background: #ccc;
                cursor: not-allowed;
            }}
            .icon {{
                font-size: 48px;
                text-align: center;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="icon">🔐</div>
        <div id="status" class="status info">
            準備完了。下のボタンをクリックしてPasskeyで認証してください。
        </div>
        <button id="authButton" onclick="authenticate()">🔑 Passkeyで認証</button>

        <script>
            // Base64URL デコード
            function base64urlDecode(str) {{
                str = str.replace(/-/g, '+').replace(/_/g, '/');
                while (str.length % 4) {{
                    str += '=';
                }}
                const binary = atob(str);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) {{
                    bytes[i] = binary.charCodeAt(i);
                }}
                return bytes.buffer;
            }}

            // Base64URL エンコード
            function base64urlEncode(buffer) {{
                const bytes = new Uint8Array(buffer);
                let binary = '';
                for (let i = 0; i < bytes.length; i++) {{
                    binary += String.fromCharCode(bytes[i]);
                }}
                return btoa(binary).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, '');
            }}

            async function authenticate() {{
                const statusDiv = document.getElementById('status');
                const button = document.getElementById('authButton');

                try {{
                    button.disabled = true;
                    statusDiv.className = 'status info';
                    statusDiv.textContent = '⏳ Passkeyで認証中...デバイスの指示に従ってください';

                    // WebAuthn認証リクエスト
                    const publicKeyCredentialRequestOptions = {{
                        challenge: base64urlDecode('{challenge}'),
                        timeout: 60000,
                        rpId: '{rp_id}',
                        userVerification: 'required'
                    }};

                    const credential = await navigator.credentials.get({{
                        publicKey: publicKeyCredentialRequestOptions
                    }});

                    if (!credential) {{
                        throw new Error('認証がキャンセルされました');
                    }}

                    // 認証成功
                    statusDiv.className = 'status success';
                    statusDiv.textContent = '✓ Passkey認証が成功しました！';

                    // 認証データを準備
                    const response = credential.response;
                    const result = {{
                        success: true,
                        credentialId: base64urlEncode(credential.rawId),
                        authenticatorData: base64urlEncode(response.authenticatorData),
                        clientDataJSON: base64urlEncode(response.clientDataJSON),
                        signature: base64urlEncode(response.signature),
                        userHandle: response.userHandle ? base64urlEncode(response.userHandle) : null
                    }};

                    // Streamlitに結果を送信
                    window.parent.postMessage({{
                        type: 'webauthn_result',
                        data: result
                    }}, '*');

                }} catch (error) {{
                    console.error('WebAuthn error:', error);
                    statusDiv.className = 'status error';

                    if (error.name === 'NotAllowedError') {{
                        statusDiv.textContent = '✗ 認証がキャンセルされました';
                    }} else if (error.name === 'NotSupportedError') {{
                        statusDiv.textContent = '✗ このブラウザはPasskeyをサポートしていません';
                    }} else {{
                        statusDiv.textContent = '✗ エラー: ' + error.message;
                    }}

                    // エラーをStreamlitに送信
                    window.parent.postMessage({{
                        type: 'webauthn_result',
                        data: {{
                            success: false,
                            error: error.message
                        }}
                    }}, '*');

                    button.disabled = false;
                }}
            }}
        </script>
    </body>
    </html>
    """

    # コンポーネントを表示
    result = components.html(webauthn_html, height=300)

    return result


def webauthn_delete(username: str, rp_name: str = "AP2 Demo"):
    """
    WebAuthn（Passkey）の削除を実行

    注意: JavaScriptからPasskeyを直接削除することはできないため、
    ユーザーにブラウザの設定から削除する方法を案内します。

    Args:
        username: ユーザー名
        rp_name: Relying Party名

    Returns:
        削除確認結果
    """

    # WebAuthn削除コンポーネント
    webauthn_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 20px;
                background: #f8f9fa;
                border-radius: 10px;
            }}
            .status {{
                padding: 15px;
                margin: 10px 0;
                border-radius: 8px;
                font-size: 14px;
                line-height: 1.6;
            }}
            .status.warning {{
                background: #fff3e0;
                border-left: 4px solid #ff9800;
                color: #e65100;
            }}
            .status.info {{
                background: #e3f2fd;
                border-left: 4px solid #2196f3;
                color: #1565c0;
            }}
            .status.success {{
                background: #e8f5e9;
                border-left: 4px solid #4caf50;
                color: #2e7d32;
            }}
            button {{
                background: #f44336;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
                margin: 10px 0;
            }}
            button:hover {{
                background: #d32f2f;
            }}
            button.secondary {{
                background: #757575;
            }}
            button.secondary:hover {{
                background: #616161;
            }}
            button:disabled {{
                background: #ccc;
                cursor: not-allowed;
            }}
            .icon {{
                font-size: 48px;
                text-align: center;
                margin: 20px 0;
            }}
            .instructions {{
                background: white;
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
                border: 1px solid #e0e0e0;
            }}
            .instructions h3 {{
                margin-top: 0;
                color: #424242;
                font-size: 16px;
            }}
            .instructions ol {{
                margin: 10px 0;
                padding-left: 20px;
            }}
            .instructions li {{
                margin: 8px 0;
                color: #616161;
            }}
            .platform-section {{
                margin: 10px 0;
                padding: 10px;
                background: #f5f5f5;
                border-radius: 5px;
            }}
            .platform-section strong {{
                color: #1976d2;
            }}
        </style>
    </head>
    <body>
        <div class="icon">🗑️</div>
        <div id="status" class="status warning">
            <strong>⚠️ Passkeyの削除について</strong><br>
            サーバー側の登録情報を削除しますが、デバイスに保存されているPasskeyは手動で削除する必要があります。
        </div>

        <div class="instructions">
            <h3>📱 デバイスからPasskeyを削除する方法</h3>

            <div class="platform-section">
                <strong>🍎 iOS/iPadOS:</strong>
                <ol>
                    <li>設定アプリを開く</li>
                    <li>「パスワード」をタップ</li>
                    <li>「{rp_name}」を検索</li>
                    <li>パスキーを選択して削除</li>
                </ol>
            </div>

            <div class="platform-section">
                <strong>🍏 macOS:</strong>
                <ol>
                    <li>システム設定を開く</li>
                    <li>「パスワード」をクリック</li>
                    <li>「{rp_name}」を検索</li>
                    <li>パスキーを選択して削除</li>
                </ol>
            </div>

            <div class="platform-section">
                <strong>🤖 Android:</strong>
                <ol>
                    <li>設定アプリを開く</li>
                    <li>「パスワードとアカウント」→「Google パスワード マネージャー」</li>
                    <li>「パスキー」タブを選択</li>
                    <li>「{rp_name}」を検索して削除</li>
                </ol>
            </div>

            <div class="platform-section">
                <strong>🌐 Chrome/Edge (Windows):</strong>
                <ol>
                    <li>ブラウザの設定を開く</li>
                    <li>「パスワード」セクションへ</li>
                    <li>「パスキー」を探す</li>
                    <li>「{rp_name}」を検索して削除</li>
                </ol>
            </div>
        </div>

        <button id="deleteButton" onclick="confirmDelete()">🗑️ サーバー側の登録を削除</button>
        <button class="secondary" onclick="cancel()">キャンセル</button>

        <script>
            function confirmDelete() {{
                const statusDiv = document.getElementById('status');
                const button = document.getElementById('deleteButton');

                button.disabled = true;
                statusDiv.className = 'status success';
                statusDiv.innerHTML = '<strong>✓ サーバー側の登録を削除しました</strong><br>デバイスからPasskeyを削除するには、上記の手順に従ってください。';

                // Streamlitに結果を送信
                window.parent.postMessage({{
                    type: 'webauthn_delete_result',
                    data: {{
                        success: true,
                        message: 'サーバー側の登録を削除しました'
                    }}
                }}, '*');
            }}

            function cancel() {{
                // キャンセルをStreamlitに通知
                window.parent.postMessage({{
                    type: 'webauthn_delete_result',
                    data: {{
                        success: false,
                        cancelled: true
                    }}
                }}, '*');
            }}
        </script>
    </body>
    </html>
    """

    # コンポーネントを表示
    result = components.html(webauthn_html, height=700)

    return result


def webauthn_register(username: str, user_id: str, rp_name: str = "AP2 Demo", rp_id: str = "localhost"):
    """
    WebAuthn（Passkey）の登録を実行

    Args:
        username: ユーザー名
        user_id: ユーザーID
        rp_name: Relying Party名
        rp_id: Relying Party ID

    Returns:
        登録結果
    """

    # チャレンジを生成
    challenge = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')

    # WebAuthn JavaScriptコンポーネント（登録用）
    webauthn_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 20px;
                background: #f8f9fa;
                border-radius: 10px;
            }}
            .status {{
                padding: 15px;
                margin: 10px 0;
                border-radius: 8px;
                font-size: 14px;
            }}
            .status.info {{
                background: #e3f2fd;
                border-left: 4px solid #2196f3;
                color: #1565c0;
            }}
            .status.success {{
                background: #e8f5e9;
                border-left: 4px solid #4caf50;
                color: #2e7d32;
            }}
            .status.error {{
                background: #ffebee;
                border-left: 4px solid #f44336;
                color: #c62828;
            }}
            button {{
                background: #4caf50;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
                margin: 10px 0;
            }}
            button:hover {{
                background: #45a049;
            }}
            button:disabled {{
                background: #ccc;
                cursor: not-allowed;
            }}
            .icon {{
                font-size: 48px;
                text-align: center;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="icon">🔑</div>
        <div id="status" class="status info">
            Passkeyを登録します。下のボタンをクリックしてください。
        </div>
        <button id="registerButton" onclick="register()">✨ Passkeyを登録</button>

        <script>
            // Base64URL デコード
            function base64urlDecode(str) {{
                str = str.replace(/-/g, '+').replace(/_/g, '/');
                while (str.length % 4) {{
                    str += '=';
                }}
                const binary = atob(str);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) {{
                    bytes[i] = binary.charCodeAt(i);
                }}
                return bytes.buffer;
            }}

            // Base64URL エンコード
            function base64urlEncode(buffer) {{
                const bytes = new Uint8Array(buffer);
                let binary = '';
                for (let i = 0; i < bytes.length; i++) {{
                    binary += String.fromCharCode(bytes[i]);
                }}
                return btoa(binary).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, '');
            }}

            // 文字列をUint8Arrayに変換
            function str2ab(str) {{
                const encoder = new TextEncoder();
                return encoder.encode(str);
            }}

            async function register() {{
                const statusDiv = document.getElementById('status');
                const button = document.getElementById('registerButton');

                try {{
                    button.disabled = true;
                    statusDiv.className = 'status info';
                    statusDiv.textContent = '⏳ Passkeyを登録中...デバイスの指示に従ってください';

                    // WebAuthn登録リクエスト
                    const publicKeyCredentialCreationOptions = {{
                        challenge: base64urlDecode('{challenge}'),
                        rp: {{
                            name: '{rp_name}',
                            id: '{rp_id}'
                        }},
                        user: {{
                            id: str2ab('{user_id}'),
                            name: '{username}',
                            displayName: '{username}'
                        }},
                        pubKeyCredParams: [
                            {{ alg: -7, type: 'public-key' }},  // ES256
                            {{ alg: -257, type: 'public-key' }}  // RS256
                        ],
                        timeout: 60000,
                        authenticatorSelection: {{
                            authenticatorAttachment: 'platform',
                            userVerification: 'required',
                            residentKey: 'preferred'
                        }},
                        attestation: 'direct'
                    }};

                    const credential = await navigator.credentials.create({{
                        publicKey: publicKeyCredentialCreationOptions
                    }});

                    if (!credential) {{
                        throw new Error('登録がキャンセルされました');
                    }}

                    // 登録成功
                    statusDiv.className = 'status success';
                    statusDiv.textContent = '✓ Passkeyの登録が成功しました！';

                    // 登録データを準備
                    const response = credential.response;
                    const result = {{
                        success: true,
                        credentialId: base64urlEncode(credential.rawId),
                        attestationObject: base64urlEncode(response.attestationObject),
                        clientDataJSON: base64urlEncode(response.clientDataJSON)
                    }};

                    // Streamlitに結果を送信
                    window.parent.postMessage({{
                        type: 'webauthn_register_result',
                        data: result
                    }}, '*');

                }} catch (error) {{
                    console.error('WebAuthn error:', error);
                    statusDiv.className = 'status error';

                    if (error.name === 'NotAllowedError') {{
                        statusDiv.textContent = '✗ 登録がキャンセルされました';
                    }} else if (error.name === 'NotSupportedError') {{
                        statusDiv.textContent = '✗ このブラウザはPasskeyをサポートしていません';
                    }} else {{
                        statusDiv.textContent = '✗ エラー: ' + error.message;
                    }}

                    // エラーをStreamlitに送信
                    window.parent.postMessage({{
                        type: 'webauthn_register_result',
                        data: {{
                            success: false,
                            error: error.message
                        }}
                    }}, '*');

                    button.disabled = false;
                }}
            }}
        </script>
    </body>
    </html>
    """

    # コンポーネントを表示
    result = components.html(webauthn_html, height=300)

    return result


