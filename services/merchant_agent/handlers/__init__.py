"""
v2/services/merchant_agent/handlers/__init__.py

A2Aメッセージハンドラーモジュール
"""

from .intent_handler import handle_intent_mandate
from .product_handler import handle_product_search_request
from .cart_handler import handle_cart_selection, handle_cart_request
from .payment_handler import handle_payment_request

__all__ = [
    'handle_intent_mandate',
    'handle_product_search_request',
    'handle_cart_selection',
    'handle_cart_request',
    'handle_payment_request',
]
