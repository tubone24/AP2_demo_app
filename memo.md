AP2プロトコルにおける「Human Present Transaction」（ユーザー立ち会い型取引）のシーケンスフローについて、A2A通信をベースとした実装例に基づき、各ステップの具体的処理、通信詳細、および背景情報を以下の通りに解説します。

このフローは、AIエージェント（ショッピングエージェント、マーチャントエージェント、資格情報プロバイダー）が**A2Aプロトコル**を用いて連携することを前提としています。

### 背景情報：なぜこのフローが必要なのか

既存の決済インフラは、自律的なAIエージェントによる取引を想定していません。AP2プロトコルは、エージェント取引における「信頼の危機」に対処するために設計されました。特に「Human Present Transaction」では、以下の目的のために詳細なシーケンスが必要です。

1.  **検証可能な意図の確立 (Verifiable Intent)**: エージェントの「幻覚（Hallucination）」や誤解を防ぐため、ユーザーの購入意図と最終的な購入内容を、改ざん不可能なデジタル証明書（VDC）に紐づけて暗号署名する。
2.  **明確な説明責任 (Clear Accountability)**: 取引にエラーや不正が発生した場合に、誰が責任を負うかを判断するための**監査可能なデジタル証拠（Cart Mandate, Intent Mandate）**を提供するため。
3.  **セキュリティの確保**: 機密性の高い支払い情報（PCIデータ）が、ショッピングエージェントなどの非専門的なエンティティにアクセスされるのを防ぎ、**Credentials Provider (CP)** が排他的に管理するため。

---

### Human Present Transaction 詳細シーケンスフロー

| ステップ | アクター | 処理内容と通信詳細 | 背景情報（なぜこの処理が必要か） |
| :--- | :--- | :--- | :--- |
| **1** | User → SA (Shopping Agent) | **Shopping Prompts (購買指示)**: ユーザーが、購買に必要なタスク（例：「このランニングシューズを買って」）を自然言語でSAに委任します。 | ユーザーがコマースタスクを開始し、SAに実行権限を委譲する初期段階です。 |
| **2** | SA → User | **Intent Mandate Confirmation**: SAは、ユーザーの要求を理解した内容をユーザーに確認のために提示します。 | エージェントの理解がユーザーの意図と合致しているかを確認し、誤解釈（「Hallucination」）を防ぐためです。 |
| **3** | User → SA | **Confirm (承認)**: ユーザーはSAの理解した内容を承認します。 | エージェントが次のステップに進むための初期の合意形成です。 |
| **4, 5** | User → SA | **(Optional) CP / Shipping Address (CP/配送先住所の指定)**: ユーザーは、使用するCPや配送先住所を提供します。 | カートの価格を確定させるため、価格変動要因となる情報（配送先など）はCart Mandate作成前に確定させる必要があります。 |
| **6** | SA → CP (Credential Provider) | **Get Payment Methods (支払い方法の取得)**: SAは、CPに対して支払いコンテキストを伝え、適用可能な支払い方法（参照または暗号化形式）を要求します。 | SAは、ユーザーが持つ支払い方法とマーチャントが受け入れる方法との互換性を確認し、最適な支払い方法の選択に役立てるためです。 |
| **7** | CP → SA | **{ Payment Methods } (支払い方法リスト)**: CPは、利用可能な支払い方法をSAに返します。 | ユーザーが次のステップで、最終的な支払い方法を選択できるようにするためです。 |
| **8** | SA → MA (Merchant Agent) | **Intent Mandate (意図証明書)**: SAは、ユーザーが署名した意図証明書（Intent Mandate）をMAに渡します。 | MAは、この意図証明書に基づき、ユーザーの要求を満たすカートの作成を開始します。 |
| **9** | MA (内部処理) | **Create Cart Mandate (カート証明書の作成)**: MAは、Intent Mandateに基づき、SKU、価格、配送情報など、具体的な取引内容を定義した**Cart Mandate**を組み立てます。 | MAが具体的な注文内容を確定させる処理です。 |
| **10** | MA → M (Merchant) | **Sign Cart Mandate (カート証明書への署名)**: MAは、作成したCart Mandateを**Merchant Entity (M)** に送り、署名を要求します。 | **マーチャントがこのカートを履行することを保証する**ためです。これにより、ユーザーはマーチャントが履行を確約したカートを確認できます。 |
| **11** | M → MA | **{ Signed Cart Mandate } (署名済みカート証明書)**: マーチャントの署名が付与されたCart MandateがMAに返されます。 | マーチャント側での履行確約が完了したことを示します。 |
| **12** | MA → SA | **{ Signed Cart Mandate }**: マーチャント署名済みのCart MandateがSAに渡されます。 | SAは、最終的な取引内容をユーザーに提示する準備が整います。 |
| **13, 14** | SA ↔ CP | **Get user payment options / { payment options }**: SAがCPから最終的な支払いオプションを取得します。 | 最終的なカート内容（ステップ12）に基づいて、CPが最も適切な支払いオプションを絞り込むため、またはリスク要件（エージェント取引のセキュリティ/トークン化要件）を満たすステップアップが必要な場合に備えます。 |
| **15a, 15b** | SA → User | **Show Cart Mandate / Payment Options Prompt (最終確認)**: SAは、マーチャントが保証した最終的なカート内容と支払いオプションを、信頼されたインターフェース上でユーザーに提示します。 | これは**不可欠な負荷担保ステップ**です。ユーザーが購入内容をすべて検証し、承認に進むためです。 |
| **16** | User → SA | **Payment Method Selection (支払い方法の選択)**: ユーザーは提示されたオプションから、使用する特定の支払い方法を選択します。 | どの金融手段をチャージするかを確定させます。 |
| **17** | SA → CP | **Get Payment Method Token (支払い方法トークンの取得)**: 選択された支払い方法のトークンをCPに要求します。 | 実際の支払いに使用するセキュアなトークンを取得し、**SAが機密性の高いPCIデータに触れるのを防ぎます**。 |
| **18** | CP → SA | **{ Token } (トークン)**: CPはSAにトークンを返します。 | トークンは、Payment Mandateの構成要素となります。 |
| **19** | SA (内部処理) | **Create Payment Mandate (決済証明書の作成)**: SAは、カートの内容、エージェントの関与、取引様式（Human Present）などの信号を含む**Payment Mandate**を作成します。 | このVDCは、取引承認メッセージとともにネットワーク/発行体に送られ、**エージェント取引であることを可視化する**役割を果たします。 |
| **20** | SA → User | **Redirect to trusted device surface { PM, CM } (信頼されたデバイス画面へのリダイレクト)**: ユーザーは、購入を最終承認し、暗号署名を行うための信頼されたデバイス画面（例：ハードウェアキー、生体認証）にリダイレクトされます。 | ユーザーがハードウェア支援キーなどで署名し、**取引に対する否認不能な最終承認（Cart Mandateの署名）**を生成するためです。 |
| **21** | User (デバイス処理) | **User confirms purchase & device creates attestation (ユーザー承認と証明の生成)**: ユーザーが購入を承認し、デバイスがその承認を示す暗号署名（Attestation）を生成します。 | **Verifiable Intent**を確立する最も重要なステップです。この署名が、紛争解決時の強力な証拠となります。 |
| **22** | User → SA | **{ Attestation } (証明)**: ユーザーの暗号署名がSAに返されます。 | SAがこの署名をペイメントマシーンに渡すために必要です。 |
| **23** | SA → CP | **Payment Mandate + Attestation**: SAは、完成したPayment MandateとユーザーのAttestationをCPに送信します。 | CPは、必要に応じてネットワークへのトークン化呼び出しを行い、必要な補足データと共に支払いエージェントトークンを要求します。 |
| **24** | SA → MA | **Purchase { PM + Attestation } (購入の実行)**: SAはMAに対して、購入の実行を要求します。 | 注文を確定させ、決済フローをトリガーします。 |
| **25** | MA → MPP (Merchant Payment Processor) | **Initiate payment { PM + Attestation } (支払い開始)**: MAは、取引の構成とネットワークへの送信をMPPに委任します。 | MPPは、発行体に対して承認要求を送信する責任を負うエンティティです。 |
| **26** | MPP → CP | **Request payment credentials { Payment Mandate } (決済資格情報の要求)**: MPPは、決済処理に必要な資格情報（トークンなど）をCPに要求します。 | MPPがネットワークに送信する取引承認メッセージを構築するため、CPが管理するセキュアな支払い情報が必要です。 |
| **27** | CP → MPP | **{ Payment Credentials } (決済資格情報)**: CPは、MPPに要求された決済資格情報を提供します。 | 支払いの実行に必要な情報がセキュアに渡されます。 |
| **28** | MPP (内部処理) | **Process payment (決済処理)**: MPPは、標準的な取引承認メッセージ（**Payment Mandate**を付加したもの）を構築し、ネットワーク/発行体（Issuer）に送付します。 | ネットワーク/発行体は、Payment Mandateの信号（エージェントの関与など）を考慮して承認/拒否/チャレンジを決定します。 |
| **29** | MPP → CP | **Payment receipt (決済レシート)**: 決済結果がCPに伝達されます。 | CPは、ユーザーの支払い管理エンティティとして、取引結果を確認・記録する必要があります。 |
| **30** | MPP → MA | **Payment receipt**: 決済結果がMAに伝達されます。 | マーチャント側は、注文を履行（商品発送など）するために、支払い成功の確認が必要です。 |
| **31** | MA → SA | **Payment receipt**: 決済結果がSAに伝達されます。 | SAはユーザーへの通知準備を行います。 |
| **32** | SA → User | **Purchase completed + receipt (購入完了とレシート)**: SAはユーザーに購入が完了したこととレシートを通知します。 | 最終的なユーザー体験の完了です。 |

### 通信プロトコルとペイロードの補足

このフローは、エージェント間の通信に**A2A (Agent-to-Agent) プロトコル**を使用することを想定しています。A2Aは、エージェント間でセキュアかつ協調的な通信を行うためのオープンスタンダードです。

特に重要なVDC（Verifiable Digital Credentials）のペイロード例は以下の通りです。これらはJSON形式の暗号署名されたオブジェクトとして交換されます。

#### 1. Cart Mandate ペイロード (例)
**目的**: ユーザーの購入意思を具体的な商品と金額に紐づけ、マーチャントが履行を確約した証拠を提供する。
```json
{
  "contents": {
    "id": "cart_shoes_123",
    "user_signature_required": false, // 署名前はfalse
    "payment_request": {
      "method_data": [
        {
          "supported_methods": "CARD",
          "data": {
            "payment_processor_url": "http://example.com/pay" // 通信先/プロセッサ情報
          }
        }
      ],
      "details": {
        "id": "order_shoes_123",
        "displayItems": [
          {
            "label": "Nike Air Max 90",
            "amount": { "currency": "USD", "value": 120.0 }
          }
        ],
        "total": {
          "label": "Total",
          "amount": { "currency": "USD", "value": 120.0 }
        }
      }
    }
  },
  "merchant_signature": "sig_merchant_shoes_abc1", // ステップ10, 11で付与
  "timestamp": "2025-08-26T19:36:36.377022Z"
}
```

#### 2. Payment Mandate ペイロード (例)
**目的**: 決済ネットワーク/発行体に対し、この取引がAIエージェントによるものであること（AI Agent presence）と、その様式（Human Present v/s Not Present）を可視化する。
```json
{
  "payment_details": {
    "cart_mandate": "<user-signed hash of the cart mandate>", // Cart Mandateへの参照
    "payment_request_id": "order_shoes_123",
    "merchant_agent_card": {
      "name": "MerchantAgent"
    },
    "payment_method": {
      "supported_methods": "CARD",
      "data": {
        "token": "xyz789" // ステップ18で取得したトークン
      }
    },
    "amount": {
      "currency": "USD",
      "value": 120.0
    },
    "risk_info": {
      "device_imei": "abc123" // リスク信号を含む
    },
    "display_info": "<image bytes>"
  },
  "creation_time": "2025-08-26T19:36:36.377022Z"
}
```