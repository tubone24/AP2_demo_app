"""
v2/common/receipt_generator.py

AP2 Protocol v2 - 領収書PDF生成モジュール
トランザクション完了後の領収書をPDFとして生成

v1のreceipt_generator.pyをv2のDict構造に適応
"""

from io import BytesIO
from datetime import datetime
from typing import Dict, Any, Optional
import logging

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

logger = logging.getLogger(__name__)


def generate_receipt_pdf(
    transaction_result: Dict[str, Any],
    cart_mandate: Optional[Dict[str, Any]],
    payment_mandate: Dict[str, Any],
    user_name: str
) -> BytesIO:
    """
    領収書PDFを生成

    AP2仕様準拠：CartMandateがNoneの場合は、PaymentMandateから取得可能な情報のみで領収書を生成

    Args:
        transaction_result: トランザクション結果（Dict形式）
        cart_mandate: カート情報（Dict形式、Noneの場合あり）
        payment_mandate: 支払い情報（Dict形式）
        user_name: ユーザー名

    Returns:
        BytesIO: 生成されたPDFのバイトストリーム
    """
    logger.info(f"[ReceiptGenerator] Generating PDF receipt for transaction: {transaction_result.get('id')}")

    # BytesIOオブジェクトを作成（メモリ上にPDFを生成）
    buffer = BytesIO()

    # PDFキャンバスを作成
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # 日本語フォントを登録
    try:
        pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
        font_name = 'HeiseiKakuGo-W5'
        logger.debug("[ReceiptGenerator] Using Japanese font: HeiseiKakuGo-W5")
    except Exception as e:
        # フォールバック: Helvetica（日本語非対応）
        font_name = 'Helvetica'
        logger.warning(f"[ReceiptGenerator] Failed to load Japanese font, using Helvetica: {e}")

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
    c.drawString(60 * mm, y_position, transaction_result.get("id", "N/A"))
    y_position -= 5 * mm

    # ステータス
    c.drawString(25 * mm, y_position, f"ステータス:")
    status = transaction_result.get("status", "unknown").upper()
    c.drawString(60 * mm, y_position, status)
    y_position -= 5 * mm

    # 承認日時
    c.drawString(25 * mm, y_position, f"承認日時:")
    authorized_at = transaction_result.get("authorized_at", "N/A")
    c.drawString(60 * mm, y_position, authorized_at)
    y_position -= 5 * mm

    # キャプチャ日時
    c.drawString(25 * mm, y_position, f"決済日時:")
    captured_at = transaction_result.get("captured_at", "N/A")
    c.drawString(60 * mm, y_position, captured_at)
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

    # 支払い方法
    payment_method = payment_mandate.get("payment_method", {})
    brand = payment_method.get("brand", "card").upper()
    last4 = payment_method.get("last4", "****")
    c.drawString(25 * mm, y_position, f"支払い方法:")
    payment_method_text = f"{brand} ****{last4}"
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
    # AP2準拠：CartMandateがない場合はPaymentMandateから情報を取得
    if cart_mandate:
        # AP2準拠：contents.merchant_nameから取得
        contents = cart_mandate.get("contents", {})
        merchant_name = contents.get("merchant_name", "Unknown Merchant")
        # _metadataからmerchant_idを取得
        merchant_id = cart_mandate.get("_metadata", {}).get("merchant_id", "N/A")
    else:
        merchant_name = payment_mandate.get("payee_name", "Unknown Merchant")
        merchant_id = payment_mandate.get("payee_id", "N/A")

    c.drawString(60 * mm, y_position, merchant_name)
    y_position -= 5 * mm

    c.drawString(25 * mm, y_position, f"店舗ID:")
    c.drawString(60 * mm, y_position, merchant_id)
    y_position -= 10 * mm

    # --- 購入商品 ---
    c.setFont(font_name, 12)
    c.drawString(20 * mm, y_position, "購入商品")
    y_position -= 7 * mm

    c.setFont(font_name, 10)
    c.line(20 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
    y_position -= 5 * mm

    # AP2準拠：CartMandateがない場合は詳細情報なし
    if cart_mandate:
        # AP2準拠：contents.payment_request.detailsから取得
        contents = cart_mandate.get("contents", {})
        payment_request = contents.get("payment_request", {})
        details = payment_request.get("details", {})
        display_items = details.get("display_items", [])

        # _metadataからraw_itemsを取得（数量情報）
        raw_items = cart_mandate.get("_metadata", {}).get("raw_items", [])

        # テーブルヘッダー
        c.drawString(25 * mm, y_position, "商品名")
        c.drawRightString(100 * mm, y_position, "数量")
        c.drawRightString(130 * mm, y_position, "単価")
        c.drawRightString(160 * mm, y_position, "小計")
        y_position -= 5 * mm

        # 商品リスト（refund_period > 0のものだけが商品）
        product_items = [item for item in display_items if item.get("refund_period", 0) > 0]
        for idx, item in enumerate(product_items):
            # 商品名（長い場合は切り詰め）
            item_name = item.get("label", "Unknown Item")[:30]
            c.drawString(25 * mm, y_position, item_name)

            # 数量（_metadata.raw_itemsから取得）
            quantity = 1
            if idx < len(raw_items):
                quantity = raw_items[idx].get("quantity", 1)
            c.drawRightString(100 * mm, y_position, str(quantity))

            # 単価（小計 ÷ 数量）
            item_amount = item.get("amount", {})
            item_value = float(item_amount.get("value", 0))
            unit_price = item_value / quantity if quantity > 0 else 0
            unit_price_str = f"¥{unit_price:,.0f}"
            c.drawRightString(130 * mm, y_position, unit_price_str)

            # 小計（AP2準拠のamount構造）
            total_price_str = _format_amount_ap2(item_amount)
            c.drawRightString(160 * mm, y_position, total_price_str)

            y_position -= 5 * mm

        y_position -= 3 * mm

        # --- 金額詳細 ---
        c.line(110 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
        y_position -= 5 * mm

        # 小計、税金、配送料を取得（refund_periodで判別）
        subtotal_value = 0.0
        tax_value = 0.0
        shipping_value = 0.0

        for item in display_items:
            item_amount = item.get("amount", {})
            item_value = float(item_amount.get("value", 0))
            refund_period = item.get("refund_period", 0)
            label = item.get("label", "")

            if refund_period > 0:
                # 商品
                subtotal_value += item_value
            elif "税" in label or "tax" in label.lower():
                # 税金
                tax_value += item_value
            elif "送料" in label or "shipping" in label.lower():
                # 配送料
                shipping_value += item_value

        # 小計
        c.drawString(110 * mm, y_position, "小計:")
        c.drawRightString(160 * mm, y_position, f"¥{subtotal_value:,.0f}")
        y_position -= 5 * mm

        # 税金
        c.drawString(110 * mm, y_position, "税金:")
        c.drawRightString(160 * mm, y_position, f"¥{tax_value:,.0f}")
        y_position -= 5 * mm

        # 配送料
        c.drawString(110 * mm, y_position, "配送料:")
        c.drawRightString(160 * mm, y_position, f"¥{shipping_value:,.0f}")
        y_position -= 5 * mm

        # 合計金額（太字）
        c.line(110 * mm, y_position + 2 * mm, width - 20 * mm, y_position + 2 * mm)
        y_position -= 5 * mm

        c.setFont(font_name, 12)
        c.drawString(110 * mm, y_position, "合計金額:")
        total_item = details.get("total", {})
        total_amount = total_item.get("amount", {})
        total_str = _format_amount_ap2(total_amount)
        c.drawRightString(160 * mm, y_position, total_str)
        y_position -= 10 * mm

    else:
        # CartMandateがない場合は合計金額のみ表示
        c.drawString(25 * mm, y_position, "商品詳細情報は利用できません")
        y_position -= 8 * mm

        # 合計金額のみ表示（PaymentMandateから取得）
        c.setFont(font_name, 12)
        c.drawString(110 * mm, y_position, "合計金額:")
        total = payment_mandate.get("amount", {})
        total_str = _format_amount(total)
        c.drawRightString(160 * mm, y_position, total_str)
        y_position -= 10 * mm

    # --- フッター ---
    c.setFont(font_name, 8)
    footer_text = "AP2 Protocol v2 Demo - Secure Transaction System"
    c.drawCentredString(width / 2, 20 * mm, footer_text)

    c.setFont(font_name, 7)
    footer_note = "この領収書はAP2プロトコルに基づいて発行されました。"
    c.drawCentredString(width / 2, 15 * mm, footer_note)

    # PDFを保存
    c.showPage()
    c.save()

    # バッファの先頭に移動
    buffer.seek(0)

    logger.info(f"[ReceiptGenerator] PDF receipt generated successfully")

    return buffer


def _format_amount(amount: Dict[str, Any]) -> str:
    """
    Amount（Dict形式）を文字列にフォーマット（旧バージョン用、互換性のため保持）

    Args:
        amount: {"value": "10000", "currency": "JPY"} 形式

    Returns:
        str: "¥10,000" のようなフォーマット済み文字列
    """
    if not amount:
        return "¥0"

    value = amount.get("value", "0")
    currency = amount.get("currency", "JPY")

    # valueがセント単位（JPY cents）の場合は円に変換
    # v2ではセント単位で扱っているため、100で割る
    try:
        value_cents = int(value)
        value_yen = value_cents / 100
        formatted_value = f"{value_yen:,.0f}"
    except (ValueError, TypeError):
        formatted_value = str(value)

    # 通貨記号
    currency_symbol = {
        "JPY": "¥",
        "USD": "$",
        "EUR": "€"
    }.get(currency, currency)

    return f"{currency_symbol}{formatted_value}"


def _format_amount_ap2(amount: Dict[str, Any]) -> str:
    """
    AP2準拠のAmount（Dict形式）を文字列にフォーマット

    AP2仕様では、valueは既に実際の金額（float）として格納されているため、
    セント変換は不要

    Args:
        amount: {"value": 10000.0, "currency": "JPY"} 形式（AP2準拠）

    Returns:
        str: "¥10,000" のようなフォーマット済み文字列
    """
    if not amount:
        return "¥0"

    value = amount.get("value", 0)
    currency = amount.get("currency", "JPY")

    # AP2準拠：valueは既に実際の金額（float）
    try:
        value_float = float(value)
        formatted_value = f"{value_float:,.0f}"
    except (ValueError, TypeError):
        formatted_value = "0"

    # 通貨記号
    currency_symbol = {
        "JPY": "¥",
        "USD": "$",
        "EUR": "€"
    }.get(currency, currency)

    return f"{currency_symbol}{formatted_value}"