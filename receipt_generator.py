"""
AP2 Protocol - 領収書PDF生成モジュール
トランザクション完了後の領収書をPDFとして生成
"""

from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont


def generate_receipt_pdf(transaction_result, cart_mandate, payment_mandate, user_name: str) -> BytesIO:
    """
    領収書PDFを生成

    Args:
        transaction_result: トランザクション結果
        cart_mandate: カート情報
        payment_mandate: 支払い情報
        user_name: ユーザー名

    Returns:
        BytesIO: 生成されたPDFのバイトストリーム
    """
    # BytesIOオブジェクトを作成（メモリ上にPDFを生成）
    buffer = BytesIO()

    # PDFキャンバスを作成
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # 日本語フォントを登録
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
        font_name = 'HeiseiKakuGo-W5'
    except:
        # フォールバック: Helvetica（日本語非対応）
        font_name = 'Helvetica'

    # --- ヘッダー部分 ---
    c.setFont(font_name, 24)
    c.drawCentredString(width / 2, height - 40 * mm, "領収書 / RECEIPT")

    # 発行日
    c.setFont(font_name, 10)
    issue_date = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
    c.drawRightString(width - 20 * mm, height - 50 * mm, f"発行日: {issue_date}")

    # --- トランザクション情報 ---
    y_position = height - 70 * mm

    c.setFont(font_name, 12)
    c.drawString(20 * mm, y_position, "トランザクション情報")
    y_position -= 7 * mm

    c.setFont(font_name, 10)
    # 線を引く
    c.line(20 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
    y_position -= 5 * mm

    # トランザクションID
    c.drawString(25 * mm, y_position, f"取引ID:")
    c.drawString(60 * mm, y_position, transaction_result.id)
    y_position -= 5 * mm

    # ステータス
    c.drawString(25 * mm, y_position, f"ステータス:")
    c.drawString(60 * mm, y_position, transaction_result.status.value.upper())
    y_position -= 5 * mm

    # 承認日時
    c.drawString(25 * mm, y_position, f"承認日時:")
    c.drawString(60 * mm, y_position, transaction_result.authorized_at or "N/A")
    y_position -= 5 * mm

    # キャプチャ日時
    c.drawString(25 * mm, y_position, f"決済日時:")
    c.drawString(60 * mm, y_position, transaction_result.captured_at or "N/A")
    y_position -= 10 * mm

    # --- 支払い者情報 ---
    c.setFont(font_name, 12)
    c.drawString(20 * mm, y_position, "支払い者情報")
    y_position -= 7 * mm

    c.setFont(font_name, 10)
    c.line(20 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
    y_position -= 5 * mm

    c.drawString(25 * mm, y_position, f"氏名:")
    c.drawString(60 * mm, y_position, user_name)
    y_position -= 5 * mm

    c.drawString(25 * mm, y_position, f"支払い方法:")
    payment_method_text = f"{payment_mandate.payment_method.brand.upper()} ****{payment_mandate.payment_method.last4}"
    c.drawString(60 * mm, y_position, payment_method_text)
    y_position -= 10 * mm

    # --- 店舗情報 ---
    c.setFont(font_name, 12)
    c.drawString(20 * mm, y_position, "店舗情報")
    y_position -= 7 * mm

    c.setFont(font_name, 10)
    c.line(20 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
    y_position -= 5 * mm

    c.drawString(25 * mm, y_position, f"店舗名:")
    c.drawString(60 * mm, y_position, cart_mandate.merchant_name)
    y_position -= 5 * mm

    c.drawString(25 * mm, y_position, f"店舗ID:")
    c.drawString(60 * mm, y_position, cart_mandate.merchant_id)
    y_position -= 10 * mm

    # --- 購入商品 ---
    c.setFont(font_name, 12)
    c.drawString(20 * mm, y_position, "購入商品")
    y_position -= 7 * mm

    c.setFont(font_name, 10)
    c.line(20 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
    y_position -= 5 * mm

    # テーブルヘッダー
    c.drawString(25 * mm, y_position, "商品名")
    c.drawRightString(100 * mm, y_position, "数量")
    c.drawRightString(130 * mm, y_position, "単価")
    c.drawRightString(160 * mm, y_position, "小計")
    y_position -= 5 * mm

    # 商品リスト
    for item in cart_mandate.items:
        c.drawString(25 * mm, y_position, item.name[:30])  # 長い商品名は切り詰め
        c.drawRightString(100 * mm, y_position, str(item.quantity))
        c.drawRightString(130 * mm, y_position, str(item.unit_price))
        c.drawRightString(160 * mm, y_position, str(item.total_price))
        y_position -= 5 * mm

    y_position -= 3 * mm

    # --- 金額詳細 ---
    c.line(110 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
    y_position -= 5 * mm

    c.drawString(110 * mm, y_position, "小計:")
    c.drawRightString(160 * mm, y_position, str(cart_mandate.subtotal))
    y_position -= 5 * mm

    c.drawString(110 * mm, y_position, "税金:")
    c.drawRightString(160 * mm, y_position, str(cart_mandate.tax))
    y_position -= 5 * mm

    c.drawString(110 * mm, y_position, "配送料:")
    c.drawRightString(160 * mm, y_position, str(cart_mandate.shipping.cost))
    y_position -= 5 * mm

    # 合計金額（太字）
    c.line(110 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
    y_position -= 5 * mm

    c.setFont(font_name, 12)
    c.drawString(110 * mm, y_position, "合計金額:")
    c.drawRightString(160 * mm, y_position, str(cart_mandate.total))
    y_position -= 10 * mm

    # --- フッター ---
    c.setFont(font_name, 8)
    footer_text = "AP2 Protocol Demo - Secure Transaction System"
    c.drawCentredString(width / 2, 20 * mm, footer_text)

    c.setFont(font_name, 7)
    footer_note = "この領収書はAP2プロトコルに基づいて発行されました。"
    c.drawCentredString(width / 2, 15 * mm, footer_note)

    # PDFを保存
    c.showPage()
    c.save()

    # バッファの先頭に移動
    buffer.seek(0)

    return buffer


def demo_receipt_generation():
    """領収書生成のデモ"""
    from dataclasses import dataclass
    from ap2_types import TransactionStatus, Amount, CartItem, ShippingInfo, PaymentMethod, CardPaymentMethod, Address

    # ダミーデータを作成
    @dataclass
    class DummyTransactionResult:
        id: str = "txn_demo_12345"
        status: TransactionStatus = TransactionStatus.CAPTURED
        authorized_at: str = "2025-10-13T10:30:00Z"
        captured_at: str = "2025-10-13T10:30:05Z"
        receipt_url: str = ""

    @dataclass
    class DummyCartMandate:
        merchant_name: str = "Demo Running Shoes Store"
        merchant_id: str = "merchant_demo_001"
        items: list = None
        subtotal: str = "USD 89.99"
        tax: str = "USD 9.00"
        total: str = "USD 103.99"
        shipping: ShippingInfo = None

        def __post_init__(self):
            if self.items is None:
                self.items = [
                    CartItem(
                        id="prod_001",
                        name="Nike Air Zoom Pegasus 40",
                        description="Professional running shoes",
                        quantity=1,
                        unit_price=Amount(value="89.99", currency="USD"),
                        total_price=Amount(value="89.99", currency="USD")
                    )
                ]
            if self.shipping is None:
                self.shipping = ShippingInfo(
                    address=Address(
                        street="123 Main Street",
                        city="San Francisco",
                        state="CA",
                        postal_code="94105",
                        country="US"
                    ),
                    method="standard",
                    cost=Amount(value="5.00", currency="USD"),
                    estimated_delivery="2025-10-20"
                )

    @dataclass
    class DummyPaymentMandate:
        payment_method: CardPaymentMethod = None

        def __post_init__(self):
            if self.payment_method is None:
                self.payment_method = CardPaymentMethod(
                    type='card',
                    token='tok_demo_xxxxx',
                    last4='4242',
                    brand='visa',
                    expiry_month=12,
                    expiry_year=2026,
                    holder_name='Demo User'
                )

    transaction = DummyTransactionResult()
    cart = DummyCartMandate()
    payment = DummyPaymentMandate()

    # PDFを生成
    pdf_buffer = generate_receipt_pdf(transaction, cart, payment, "デモユーザー")

    # ファイルに保存
    with open("demo_receipt.pdf", "wb") as f:
        f.write(pdf_buffer.getvalue())

    print("✓ 領収書PDFを生成しました: demo_receipt.pdf")


if __name__ == "__main__":
    demo_receipt_generation()