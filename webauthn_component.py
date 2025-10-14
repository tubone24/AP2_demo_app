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
                    statusDiv.textContent = '✓ Passkey認証が成功しました！下の確認ボタンをクリックしてください。';

                    // 認証データを準備
                    const response = credential.response;
                    const result = {{
                        success: true,
                        credentialId: base64urlEncode(credential.rawId),
                        authenticatorData: base64urlEncode(response.authenticatorData),
                        clientDataJSON: base64urlEncode(response.clientDataJSON),
                        signature: base64urlEncode(response.signature),
                        userHandle: response.userHandle ? base64urlEncode(response.userHandle) : null,
                        timestamp: Date.now()
                    }};

                    // 結果をJSONとして画面に表示
                    const resultJson = JSON.stringify(result, null, 2);

                    // コンテナを作成
                    const container = document.createElement('div');
                    container.style.cssText = 'margin-top: 15px;';

                    // JSON表示エリア
                    const resultDiv = document.createElement('div');
                    resultDiv.style.cssText = 'padding: 15px; background: #f5f5f5; border: 1px solid #ddd; border-radius: 5px; font-family: monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word; max-height: 100px; overflow-y: auto;';
                    resultDiv.textContent = resultJson;
                    resultDiv.id = 'authResultJson';

                    // コピーボタン
                    const copyButton = document.createElement('button');
                    copyButton.textContent = '📋 クリップボードにコピー';
                    copyButton.style.cssText = 'margin-top: 10px; padding: 10px 20px; background: #4caf50; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; width: 100%;';
                    copyButton.onclick = async function() {{
                        try {{
                            await navigator.clipboard.writeText(resultJson);
                            copyButton.textContent = '✓ コピーしました！';
                            copyButton.style.background = '#2e7d32';
                            setTimeout(() => {{
                                copyButton.textContent = '📋 クリップボードにコピー';
                                copyButton.style.background = '#4caf50';
                            }}, 2000);
                        }} catch (err) {{
                            copyButton.textContent = '✗ コピー失敗';
                            copyButton.style.background = '#f44336';
                            setTimeout(() => {{
                                copyButton.textContent = '📋 クリップボードにコピー';
                                copyButton.style.background = '#4caf50';
                            }}, 2000);
                        }}
                    }};

                    container.appendChild(resultDiv);
                    container.appendChild(copyButton);
                    document.body.appendChild(container);

                    console.log('認証成功 - 結果を画面に表示:', result);

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

                    // エラー結果をJSONとして画面に表示
                    const errorResult = {{
                        success: false,
                        error: error.message,
                        timestamp: Date.now()
                    }};
                    const resultJson = JSON.stringify(errorResult, null, 2);

                    // コンテナを作成
                    const container = document.createElement('div');
                    container.style.cssText = 'margin-top: 15px;';

                    // JSON表示エリア
                    const resultDiv = document.createElement('div');
                    resultDiv.style.cssText = 'padding: 15px; background: #ffebee; border: 1px solid #f44336; border-radius: 5px; font-family: monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word; max-height: 100px; overflow-y: auto;';
                    resultDiv.textContent = resultJson;
                    resultDiv.id = 'authResultJson';

                    // コピーボタン
                    const copyButton = document.createElement('button');
                    copyButton.textContent = '📋 クリップボードにコピー';
                    copyButton.style.cssText = 'margin-top: 10px; padding: 10px 20px; background: #f44336; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; width: 100%;';
                    copyButton.onclick = async function() {{
                        try {{
                            await navigator.clipboard.writeText(resultJson);
                            copyButton.textContent = '✓ コピーしました！';
                            copyButton.style.background = '#d32f2f';
                            setTimeout(() => {{
                                copyButton.textContent = '📋 クリップボードにコピー';
                                copyButton.style.background = '#f44336';
                            }}, 2000);
                        }} catch (err) {{
                            copyButton.textContent = '✗ コピー失敗';
                            copyButton.style.background = '#b71c1c';
                            setTimeout(() => {{
                                copyButton.textContent = '📋 クリップボードにコピー';
                                copyButton.style.background = '#f44336';
                            }}, 2000);
                        }}
                    }};

                    container.appendChild(resultDiv);
                    container.appendChild(copyButton);
                    document.body.appendChild(container);

                    console.log('認証失敗 - 結果を画面に表示:', errorResult);

                    button.disabled = false;
                }}
            }}
        </script>
    </body>
    </html>
    """

    # コンポーネントを表示（認証結果JSON表示用に高さを確保）
    components.html(webauthn_html, height=550)

    # 戻り値は使用しない
    return None


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


def check_webauthn_auth_result():
    """
    ローカルストレージからWebAuthn認証結果を確認し、成功/失敗を返す

    Returns:
        bool: 認証が成功した場合True、失敗またはない場合False
    """

    # ローカルストレージから取得して表示するHTMLコンポーネント
    check_result_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 10px;
                margin: 0;
            }
            .result {
                padding: 15px;
                border-radius: 8px;
                font-size: 14px;
                margin: 5px 0;
            }
            .success {
                background: #e8f5e9;
                border-left: 4px solid #4caf50;
                color: #2e7d32;
            }
            .error {
                background: #ffebee;
                border-left: 4px solid #f44336;
                color: #c62828;
            }
            .none {
                background: #fff3e0;
                border-left: 4px solid #ff9800;
                color: #e65100;
            }
        </style>
    </head>
    <body>
        <div id="result"></div>
        <script>
            const resultDiv = document.getElementById('result');

            // ローカルストレージから認証結果を取得
            const authResultStr = localStorage.getItem('webauthn_auth_result');

            if (authResultStr) {
                try {
                    const authResult = JSON.parse(authResultStr);

                    if (authResult.success === true) {
                        resultDiv.className = 'result success';
                        resultDiv.innerHTML = '✓ <strong>認証成功:</strong> Passkey認証が完了しました';

                        // 成功を示すメタデータを設定
                        document.body.setAttribute('data-auth-result', 'success');
                    } else {
                        resultDiv.className = 'result error';
                        resultDiv.innerHTML = '✗ <strong>認証失敗:</strong> ' + (authResult.error || '認証がキャンセルまたは失敗しました');

                        // 失敗を示すメタデータを設定
                        document.body.setAttribute('data-auth-result', 'failure');
                    }

                    console.log('認証結果:', authResult);
                } catch (error) {
                    resultDiv.className = 'result error';
                    resultDiv.innerHTML = '✗ <strong>エラー:</strong> 認証結果の読み取りに失敗しました';
                    document.body.setAttribute('data-auth-result', 'error');
                    console.error('認証結果のパースエラー:', error);
                }
            } else {
                resultDiv.className = 'result none';
                resultDiv.innerHTML = '⚠️ <strong>認証結果なし:</strong> まず上のボタンでPasskey認証を実行してください';
                document.body.setAttribute('data-auth-result', 'none');
                console.log('認証結果なし');
            }
        </script>
    </body>
    </html>
    """

    # コンポーネントを表示
    components.html(check_result_html, height=80)

    # ローカルストレージから結果を読み取る（Pythonでは直接読めないので、
    # 実際にはsession_stateに保存する必要がある）
    # このデモでは、ユーザーが視覚的に確認できるようにする
    return None


def get_webauthn_auth_result():
    """
    ローカルストレージからWebAuthn認証結果（JSON）を取得してStreamlitに返す

    Returns:
        dict or None: 認証結果のJSON（タイムスタンプ、署名データなど）
    """
    import streamlit as st
    import time

    # 一意のタイムスタンプを生成（Streamlitに異なるコンテンツとして認識させるため）
    timestamp = int(time.time() * 1000)

    # ローカルストレージから取得してStreamlitに返すHTMLコンポーネント
    # HTMLコメントにタイムスタンプを含めることで、毎回異なるコンテンツとして認識される
    get_result_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <!-- Unique timestamp: {timestamp} -->
        <script>
            // Streamlit.setComponentValueを使ってデータを返す
            function setStreamlitValue(value) {{
                // iframeからparentにpostMessageで送信
                window.parent.postMessage({{
                    isStreamlitMessage: true,
                    type: "streamlit:setComponentValue",
                    value: value
                }}, "*");
            }}

            // ページロード時に実行
            window.addEventListener('load', function() {{
                // ローカルストレージから認証結果を取得
                const authResultStr = localStorage.getItem('webauthn_auth_result');

                if (authResultStr) {{
                    try {{
                        const authResult = JSON.parse(authResultStr);
                        console.log('[get_webauthn_auth_result] 認証結果を取得:', authResult);

                        // Streamlitに送信
                        setStreamlitValue(authResult);

                        // 視覚的フィードバック
                        document.body.innerHTML = '<div style="padding: 10px; background: #e8f5e9; border-left: 4px solid #4caf50; color: #2e7d32; border-radius: 5px; font-size: 13px;">✓ WebAuthn認証結果を取得しました</div>';
                    }} catch (error) {{
                        console.error('[get_webauthn_auth_result] パースエラー:', error);
                        setStreamlitValue(null);
                        document.body.innerHTML = '<div style="padding: 10px; background: #ffebee; border-left: 4px solid #f44336; color: #c62828; border-radius: 5px; font-size: 13px;">✗ 認証結果の読み取りに失敗</div>';
                    }}
                }} else {{
                    console.log('[get_webauthn_auth_result] 認証結果が見つかりません');
                    setStreamlitValue(null);
                    document.body.innerHTML = '<div style="padding: 10px; background: #fff3e0; border-left: 4px solid #ff9800; color: #e65100; border-radius: 5px; font-size: 13px;">⚠️ 認証結果が見つかりません</div>';
                }}
            }});
        </script>
    </head>
    <body>
        <div style="padding: 10px; color: #666;">読み込み中...</div>
    </body>
    </html>
    """

    # コンポーネントを表示して結果を取得（keyパラメータは不要）
    result = components.html(get_result_html, height=60)

    return result


def clear_webauthn_auth_result():
    """
    ローカルストレージのWebAuthn認証結果をクリアする

    古い認証結果がリプレイ攻撃に使われるのを防ぐため、
    新しい認証を開始する前に必ず呼び出すべき。
    """
    # ローカルストレージをクリアするHTMLコンポーネント
    clear_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 10px;
                margin: 0;
            }
            .status {
                padding: 10px;
                background: #e8f5e9;
                border-left: 4px solid #4caf50;
                color: #2e7d32;
                border-radius: 5px;
                font-size: 13px;
            }
        </style>
    </head>
    <body>
        <div id="status" class="status">🗑️ 古い認証結果をクリアしました</div>
        <script>
            // ローカルストレージから認証結果を削除
            localStorage.removeItem('webauthn_auth_result');
            console.log('[WebAuthn] ローカルストレージの認証結果をクリアしました');
        </script>
    </body>
    </html>
    """

    # コンポーネントを表示
    components.html(clear_html, height=60)
