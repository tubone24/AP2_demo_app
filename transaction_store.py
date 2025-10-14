"""
AP2 Protocol - Transaction Store
トランザクションの永続化と履歴管理
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List
import json

from ap2_types import (
    TransactionResult,
    TransactionStatus,
    PaymentMandate,
    CartMandate,
    IntentMandate
)


class TransactionStore:
    """
    トランザクションの永続化を担当

    AP2仕様に準拠したトランザクション履歴の保存・検索機能を提供。
    再検証・追跡・監査が可能な形式でトランザクションを記録する。

    機能:
    - トランザクション結果の保存
    - トランザクション履歴の検索
    - Intent Mandateごとのトランザクション集計
    - 監査ログの生成
    """

    def __init__(self, db_file: str = "./transactions_db.json"):
        """
        Transaction Storeを初期化

        Args:
            db_file: トランザクションデータベースファイルのパス
        """
        self.db_file = Path(db_file)
        self.transactions: Dict[str, Dict] = {}
        self._load_transactions()

    def _load_transactions(self) -> None:
        """トランザクション履歴をファイルから読み込む"""
        if self.db_file.exists():
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.transactions = data.get('transactions', {})
                print(f"[TransactionStore] トランザクション履歴を読み込みました: {len(self.transactions)}件")
            except Exception as e:
                print(f"[TransactionStore] トランザクション履歴の読み込みに失敗: {e}")
                self.transactions = {}
        else:
            print(f"[TransactionStore] 新しいトランザクションデータベースを作成します")
            self.transactions = {}

    def _persist(self) -> None:
        """トランザクション履歴をJSONファイルに保存"""
        try:
            # ディレクトリが存在しない場合は作成
            self.db_file.parent.mkdir(parents=True, exist_ok=True)

            # トランザクションデータを整形
            data = {
                'metadata': {
                    'version': '1.0',
                    'last_updated': datetime.utcnow().isoformat() + 'Z',
                    'total_transactions': len(self.transactions)
                },
                'transactions': self.transactions
            }

            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[TransactionStore] トランザクション履歴を保存しました: {len(self.transactions)}件")
        except Exception as e:
            print(f"[TransactionStore] トランザクション履歴の保存に失敗: {e}")

    def save_transaction(
        self,
        transaction_result: TransactionResult,
        payment_mandate: PaymentMandate,
        cart_mandate: Optional[CartMandate] = None,
        intent_mandate: Optional[IntentMandate] = None
    ) -> None:
        """
        トランザクションを保存

        Args:
            transaction_result: トランザクション結果
            payment_mandate: Payment Mandate
            cart_mandate: Cart Mandate（オプション）
            intent_mandate: Intent Mandate（オプション）
        """
        transaction_id = transaction_result.id

        # トランザクションデータを構築
        transaction_data = {
            'id': transaction_id,
            'payment_mandate_id': transaction_result.payment_mandate_id,
            'status': transaction_result.status.value,
            'amount': {
                'value': payment_mandate.amount.value,
                'currency': payment_mandate.amount.currency
            },
            'payer_id': payment_mandate.payer_id,
            'payee_id': payment_mandate.payee_id,
            'transaction_type': payment_mandate.transaction_type,
            'agent_involved': payment_mandate.agent_involved,
            'authorized_at': transaction_result.authorized_at,
            'captured_at': transaction_result.captured_at,
            'error_code': transaction_result.error_code,
            'error_message': transaction_result.error_message,
            'receipt_url': transaction_result.receipt_url,
            'verified': True,  # Verifierによる検証済みフラグ
            'saved_at': datetime.utcnow().isoformat() + 'Z'
        }

        # Cart Mandate情報を追加
        if cart_mandate:
            transaction_data['cart_mandate_id'] = cart_mandate.id
            transaction_data['merchant_id'] = cart_mandate.merchant_id
            transaction_data['merchant_name'] = cart_mandate.merchant_name

        # Intent Mandate情報を追加
        if intent_mandate:
            transaction_data['intent_mandate_id'] = intent_mandate.id
            transaction_data['intent'] = intent_mandate.intent
            transaction_data['user_id'] = intent_mandate.user_id

        # リスク情報を追加
        if payment_mandate.risk_score is not None:
            transaction_data['risk_score'] = payment_mandate.risk_score
            transaction_data['fraud_indicators'] = payment_mandate.fraud_indicators

        # Device Attestation情報を追加
        if payment_mandate.device_attestation:
            transaction_data['device_attestation'] = {
                'device_id': payment_mandate.device_attestation.device_id,
                'attestation_type': payment_mandate.device_attestation.attestation_type.value,
                'timestamp': payment_mandate.device_attestation.timestamp,
                'platform': payment_mandate.device_attestation.platform
            }

        # トランザクションを保存
        self.transactions[transaction_id] = transaction_data
        self._persist()

        print(f"[TransactionStore] トランザクションを保存しました: {transaction_id}")

    def get_transaction(self, transaction_id: str) -> Optional[Dict]:
        """
        トランザクションを取得

        Args:
            transaction_id: トランザクションID

        Returns:
            Optional[Dict]: トランザクションデータ（見つからない場合はNone）
        """
        return self.transactions.get(transaction_id)

    def get_transactions_by_intent(self, intent_mandate_id: str) -> List[Dict]:
        """
        Intent Mandateに紐づくトランザクションを取得

        Args:
            intent_mandate_id: Intent Mandate ID

        Returns:
            List[Dict]: トランザクションデータのリスト
        """
        return [
            tx for tx in self.transactions.values()
            if tx.get('intent_mandate_id') == intent_mandate_id
        ]

    def get_transactions_by_user(self, user_id: str) -> List[Dict]:
        """
        ユーザーのトランザクションを取得

        Args:
            user_id: ユーザーID

        Returns:
            List[Dict]: トランザクションデータのリスト
        """
        return [
            tx for tx in self.transactions.values()
            if tx.get('user_id') == user_id
        ]

    def get_transactions_by_merchant(self, merchant_id: str) -> List[Dict]:
        """
        マーチャントのトランザクションを取得

        Args:
            merchant_id: マーチャントID

        Returns:
            List[Dict]: トランザクションデータのリスト
        """
        return [
            tx for tx in self.transactions.values()
            if tx.get('merchant_id') == merchant_id
        ]

    def get_transactions_by_status(self, status: TransactionStatus) -> List[Dict]:
        """
        ステータスでトランザクションをフィルタ

        Args:
            status: トランザクションステータス

        Returns:
            List[Dict]: トランザクションデータのリスト
        """
        return [
            tx for tx in self.transactions.values()
            if tx.get('status') == status.value
        ]

    def count_transactions_by_intent(self, intent_mandate_id: str) -> int:
        """
        Intent Mandateに紐づくトランザクション数をカウント

        Args:
            intent_mandate_id: Intent Mandate ID

        Returns:
            int: トランザクション数
        """
        return len(self.get_transactions_by_intent(intent_mandate_id))

    def get_transaction_stats(self) -> Dict:
        """
        トランザクション統計を取得

        Returns:
            Dict: 統計情報
        """
        total = len(self.transactions)

        # ステータス別集計
        status_counts = {}
        for status in TransactionStatus:
            count = len(self.get_transactions_by_status(status))
            status_counts[status.value] = count

        # 合計金額を集計
        total_amount_by_currency = {}
        for tx in self.transactions.values():
            if tx.get('status') == TransactionStatus.CAPTURED.value:
                currency = tx['amount']['currency']
                value = float(tx['amount']['value'])

                if currency not in total_amount_by_currency:
                    total_amount_by_currency[currency] = 0.0

                total_amount_by_currency[currency] += value

        return {
            'total_transactions': total,
            'status_counts': status_counts,
            'total_amount_by_currency': total_amount_by_currency
        }

    def generate_audit_log(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """
        監査ログを生成

        Args:
            start_date: 開始日時（ISO 8601）
            end_date: 終了日時（ISO 8601）

        Returns:
            List[Dict]: 監査ログエントリのリスト
        """
        audit_log = []

        for tx in self.transactions.values():
            # 日付フィルタリング
            if start_date and tx.get('authorized_at'):
                if tx['authorized_at'] < start_date:
                    continue

            if end_date and tx.get('authorized_at'):
                if tx['authorized_at'] > end_date:
                    continue

            # 監査ログエントリを作成
            audit_entry = {
                'transaction_id': tx['id'],
                'timestamp': tx.get('authorized_at') or tx.get('saved_at'),
                'user_id': tx.get('user_id'),
                'merchant_id': tx.get('merchant_id'),
                'amount': tx['amount'],
                'status': tx['status'],
                'verified': tx.get('verified', False),
                'risk_score': tx.get('risk_score'),
                'device_attestation': bool(tx.get('device_attestation'))
            }

            audit_log.append(audit_entry)

        # タイムスタンプでソート
        audit_log.sort(key=lambda x: x['timestamp'])

        return audit_log

    def export_to_json(self, output_file: str) -> None:
        """
        トランザクション履歴をJSONファイルにエクスポート

        Args:
            output_file: 出力ファイルパス
        """
        output_path = Path(output_file)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            export_data = {
                'exported_at': datetime.utcnow().isoformat() + 'Z',
                'total_transactions': len(self.transactions),
                'statistics': self.get_transaction_stats(),
                'transactions': list(self.transactions.values())
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            print(f"[TransactionStore] トランザクション履歴をエクスポートしました: {output_file}")
        except Exception as e:
            print(f"[TransactionStore] エクスポートに失敗: {e}")

    def clear_all(self) -> None:
        """
        すべてのトランザクションをクリア（テスト用）

        警告: この操作は元に戻せません
        """
        print(f"[TransactionStore] 警告: すべてのトランザクション({len(self.transactions)}件)を削除します")
        self.transactions = {}
        self._persist()
        print(f"[TransactionStore] トランザクションをクリアしました")


def demo_transaction_store():
    """Transaction Storeのデモ"""
    from ap2_types import Amount, CardPaymentMethod
    from datetime import datetime, timedelta
    import uuid

    print("=" * 80)
    print("Transaction Store - トランザクション永続化デモ")
    print("=" * 80)

    # Transaction Storeを初期化
    store = TransactionStore("./demo_transactions_db.json")

    # デモ用トランザクションを作成
    print("\n--- トランザクションを保存 ---")

    for i in range(3):
        # TransactionResult（簡易版）
        from ap2_types import TransactionResult, TransactionStatus

        transaction_result = TransactionResult(
            id=f"txn_{uuid.uuid4().hex[:12]}",
            status=TransactionStatus.CAPTURED if i < 2 else TransactionStatus.FAILED,
            payment_mandate_id=f"payment_{i+1}",
            authorized_at=datetime.utcnow().isoformat() + 'Z',
            captured_at=datetime.utcnow().isoformat() + 'Z' if i < 2 else None,
            error_code="insufficient_funds" if i == 2 else None,
            error_message="残高不足" if i == 2 else None
        )

        # PaymentMandate（簡易版）
        from ap2_types import PaymentMandate

        now = datetime.utcnow()
        payment_mandate = PaymentMandate(
            id=f"payment_{i+1}",
            type="PaymentMandate",
            version="1.0",
            cart_mandate_id=f"cart_{i+1}",
            intent_mandate_id="intent_001",
            payment_method=CardPaymentMethod(
                type='card',
                token='tok_demo',
                last4='4242',
                brand='visa',
                expiry_month=12,
                expiry_year=2026,
                holder_name='Demo User'
            ),
            amount=Amount(value=f"{(i+1)*10}.00", currency="USD"),
            transaction_type="human_not_present",
            agent_involved=True,
            payer_id="user_demo_001",
            payee_id="merchant_demo_001",
            created_at=now.isoformat() + 'Z',
            expires_at=(now + timedelta(minutes=15)).isoformat() + 'Z',
            risk_score=25 + i*10
        )

        # トランザクションを保存
        store.save_transaction(transaction_result, payment_mandate)

        print(f"  トランザクション {i+1} を保存: {transaction_result.id}")

    # トランザクション統計を表示
    print("\n--- トランザクション統計 ---")
    stats = store.get_transaction_stats()
    print(f"  総トランザクション数: {stats['total_transactions']}")
    print(f"  ステータス別:")
    for status, count in stats['status_counts'].items():
        print(f"    - {status}: {count}件")
    print(f"  合計金額:")
    for currency, amount in stats['total_amount_by_currency'].items():
        print(f"    - {currency}: {amount:.2f}")

    # Intent別トランザクションを取得
    print("\n--- Intent別トランザクション ---")
    intent_transactions = store.get_transactions_by_intent("intent_001")
    print(f"  Intent 'intent_001' のトランザクション: {len(intent_transactions)}件")
    for tx in intent_transactions:
        print(f"    - {tx['id']}: {tx['status']} ({tx['amount']['currency']} {tx['amount']['value']})")

    # 監査ログを生成
    print("\n--- 監査ログ ---")
    audit_log = store.generate_audit_log()
    print(f"  監査ログエントリ: {len(audit_log)}件")
    for entry in audit_log:
        print(f"    - {entry['transaction_id']}: {entry['status']} at {entry['timestamp']}")

    # JSONエクスポート
    print("\n--- JSONエクスポート ---")
    store.export_to_json("./demo_transactions_export.json")

    print("\n" + "=" * 80)
    print("デモンストレーション完了!")
    print("=" * 80)


if __name__ == "__main__":
    demo_transaction_store()