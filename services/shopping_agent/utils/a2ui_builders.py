"""
A2UI (Agent-to-User Interface) Surface Builders
Based on A2UI Specification v0.9

This module provides builder functions to create A2UI-compliant surfaces
for various UI components in the shopping flow.

A2UI v0.9 Protocol Reference:
https://a2ui.org/specification/v0.9-a2ui/

Message Types:
- createSurface: Initialize a new UI surface
- updateComponents: Provide component definitions
- updateDataModel: Send/modify data for components
- deleteSurface: Remove a surface
"""

from typing import Any, Optional, List, Dict
import uuid

# Standard A2UI catalog ID
A2UI_CATALOG_ID = "https://a2ui.dev/specification/0.9/standard_catalog_definition.json"


def _generate_id(prefix: str = "comp") -> str:
    """Generate a unique component ID."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# =============================================================================
# A2UI v0.9 Protocol Message Generators
# =============================================================================

def generate_a2ui_messages(
    surface_id: str,
    components: List[Dict[str, Any]],
    data_model: Dict[str, Any],
    catalog_id: str = A2UI_CATALOG_ID
) -> List[Dict[str, Any]]:
    """
    Generate A2UI v0.9 protocol compliant message sequence.

    A2UI v0.9 does NOT have beginRendering - rendering starts automatically
    when a component with id="root" exists in the components list.

    Args:
        surface_id: Unique identifier for the surface
        components: List of component definitions (must include id="root")
        data_model: Data model for the surface
        catalog_id: Component catalog ID

    Returns:
        List of SSE event dictionaries in order:
        1. createSurface
        2. updateComponents
        3. updateDataModel
    """
    return [
        # 1. Create Surface
        {
            "type": "a2ui_create_surface",
            "surface_id": surface_id,
            "catalog_id": catalog_id
        },
        # 2. Update Components
        {
            "type": "a2ui_update_components",
            "surface_id": surface_id,
            "components": components
        },
        # 3. Update Data Model
        {
            "type": "a2ui_update_data_model",
            "surface_id": surface_id,
            "path": "/",
            "op": "replace",
            "value": data_model
        }
    ]


def generate_delete_surface_message(surface_id: str) -> Dict[str, Any]:
    """
    Generate A2UI v0.9 deleteSurface message.

    Args:
        surface_id: Surface ID to delete

    Returns:
        SSE event dictionary for deleteSurface
    """
    return {
        "type": "a2ui_delete_surface",
        "surface_id": surface_id
    }


# =============================================================================
# Shipping Form A2UI Builder
# =============================================================================

def build_shipping_form_a2ui(
    fields: list[dict],
    surface_id: Optional[str] = None
) -> dict:
    """
    Build an A2UI surface for the shipping address form.

    Args:
        fields: List of form fields with name, label, type, required, placeholder, options
        surface_id: Optional surface ID (generated if not provided)

    Returns:
        A2UI surface definition for shipping form
    """
    surface_id = surface_id or _generate_id("shipping-form")

    # Build field components
    field_components = []
    field_ids = []

    for field in fields:
        field_id = _generate_id(f"field-{field['name']}")
        field_ids.append(field_id)

        if field.get("type") == "select" and field.get("options"):
            # Use ChoicePicker for select fields
            options = [
                {
                    "id": opt["value"],
                    "label": {"literalString": opt["label"]}
                }
                for opt in field["options"]
            ]
            field_components.append({
                "id": field_id,
                "component": {
                    "ChoicePicker": {
                        "label": {"literalString": field["label"] + (" *" if field.get("required") else "")},
                        "options": options,
                        "selectedId": {"path": f"/shipping/{field['name']}"},
                        "multiSelect": False
                    }
                }
            })
        else:
            # Use TextField for text inputs
            text_field_type = "shortText"
            if field.get("type") == "email":
                text_field_type = "email"
            elif field.get("type") == "phone":
                text_field_type = "phone"
            elif field.get("type") == "number":
                text_field_type = "number"

            component_def = {
                "TextField": {
                    "label": {"literalString": field["label"] + (" *" if field.get("required") else "")},
                    "text": {"path": f"/shipping/{field['name']}"},
                    "textFieldType": text_field_type
                }
            }

            if field.get("placeholder"):
                component_def["TextField"]["placeholder"] = {"literalString": field["placeholder"]}

            # Note: TextField.required is NOT in A2UI v0.9 standard schema
            # Required indicator is shown in label text instead (e.g., "Name *")

            field_components.append({
                "id": field_id,
                "component": component_def
            })

    # Build submit button
    submit_button_text_id = _generate_id("submit-text")
    submit_button_id = _generate_id("submit-button")

    # Build column container
    column_id = _generate_id("form-column")
    # Root component must have id="root" for A2UI v0.9 auto-rendering

    components = [
        # Card wrapper (root component)
        {
            "id": "root",
            "component": {
                "Card": {
                    "child": column_id
                }
            }
        },
        # Column layout
        {
            "id": column_id,
            "component": {
                "Column": {
                    "children": field_ids + [submit_button_id],
                    "distribution": "start",
                    "gap": 12
                }
            }
        },
        # Submit button text
        {
            "id": submit_button_text_id,
            "component": {
                "Text": {
                    "text": {"literalString": "配送先を確定"}
                }
            }
        },
        # Submit button
        {
            "id": submit_button_id,
            "component": {
                "Button": {
                    "child": submit_button_text_id,
                    "primary": True,
                    "disabled": {"path": "/formInvalid"},
                    "action": {
                        "name": "submit_shipping",
                        "context": {
                            "shipping": {"path": "/shipping"}
                        }
                    }
                }
            }
        }
    ] + field_components

    # Build initial data model with validation metadata
    required_fields = [field["name"] for field in fields if field.get("required", False)]
    initial_values = {field["name"]: field.get("default", "") for field in fields}

    # Check if initial values satisfy required fields
    form_invalid = any(
        not initial_values.get(field_name)
        for field_name in required_fields
    )

    data_model = {
        "shipping": initial_values,
        "formInvalid": form_invalid,
        "_validation": {
            "requiredFields": required_fields
        }
    }

    return {
        "surfaceId": surface_id,
        "surfaceType": "shipping_form",
        "components": components,
        "dataModel": data_model
    }


def generate_shipping_form_a2ui_messages(
    fields: list[dict],
    surface_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Generate A2UI v0.9 protocol messages for shipping form.

    Args:
        fields: List of form fields
        surface_id: Optional surface ID

    Returns:
        List of SSE events (createSurface, updateComponents, updateDataModel)
    """
    surface = build_shipping_form_a2ui(fields, surface_id)
    return generate_a2ui_messages(
        surface_id=surface["surfaceId"],
        components=surface["components"],
        data_model=surface["dataModel"]
    )


# =============================================================================
# Credential Provider Selection A2UI Builder
# =============================================================================

def build_cp_selection_a2ui(
    providers: list[dict],
    surface_id: Optional[str] = None
) -> dict:
    """
    Build an A2UI surface for credential provider selection.

    Args:
        providers: List of credential providers with id, name, description, supported_methods
        surface_id: Optional surface ID (generated if not provided)

    Returns:
        A2UI surface definition for CP selection
    """
    surface_id = surface_id or _generate_id("cp-selection")

    # Build provider card components
    provider_components = []
    card_ids = []

    for index, provider in enumerate(providers):
        card_id = _generate_id(f"cp-card-{index}")
        row_id = _generate_id(f"cp-row-{index}")
        index_id = _generate_id(f"cp-index-{index}")
        info_col_id = _generate_id(f"cp-info-{index}")
        name_id = _generate_id(f"cp-name-{index}")
        desc_id = _generate_id(f"cp-desc-{index}")
        methods_id = _generate_id(f"cp-methods-{index}")

        card_ids.append(card_id)

        provider_components.extend([
            # Card
            {
                "id": card_id,
                "component": {
                    "Card": {
                        "child": row_id,
                        "action": {
                            "name": "select_credential_provider",
                            "context": {
                                "index": {"literalNumber": index + 1},
                                "providerId": {"literalString": provider["id"]}
                            }
                        }
                    }
                }
            },
            # Row layout
            {
                "id": row_id,
                "component": {
                    "Row": {
                        "children": [index_id, info_col_id],
                        "alignment": "center",
                        "gap": 12
                    }
                }
            },
            # Index number
            {
                "id": index_id,
                "component": {
                    "Text": {
                        "text": {"literalString": str(index + 1)},
                        "styleHint": "h2"
                    }
                }
            },
            # Info column
            {
                "id": info_col_id,
                "component": {
                    "Column": {
                        "children": [name_id, desc_id, methods_id],
                        "distribution": "start",
                        "gap": 4
                    }
                }
            },
            # Provider name
            {
                "id": name_id,
                "component": {
                    "Text": {
                        "text": {"literalString": provider["name"]},
                        "styleHint": "h4"
                    }
                }
            },
            # Description
            {
                "id": desc_id,
                "component": {
                    "Text": {
                        "text": {"literalString": provider.get("description", "")},
                        "styleHint": "body"
                    }
                }
            },
            # Supported methods
            {
                "id": methods_id,
                "component": {
                    "Text": {
                        "text": {"literalString": f"対応: {', '.join(provider.get('supported_methods', []))}"},
                        "styleHint": "caption"
                    }
                }
            }
        ])

    # Build list container
    # Root component must have id="root" for A2UI v0.9 auto-rendering

    components = [
        {
            "id": "root",
            "component": {
                "Column": {
                    "children": card_ids,
                    "distribution": "start",
                    "gap": 8
                }
            }
        }
    ] + provider_components

    # Build data model
    data_model = {
        "credentialProviders": [
            {
                "id": p["id"],
                "name": p["name"],
                "description": p.get("description", ""),
                "supported_methods": p.get("supported_methods", [])
            }
            for p in providers
        ],
        "selectedIndex": None
    }

    return {
        "surfaceId": surface_id,
        "surfaceType": "credential_provider_selection",
        "components": components,
        "dataModel": data_model
    }


def generate_cp_selection_a2ui_messages(
    providers: list[dict],
    surface_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Generate A2UI v0.9 protocol messages for credential provider selection.

    Args:
        providers: List of credential providers
        surface_id: Optional surface ID

    Returns:
        List of SSE events (createSurface, updateComponents, updateDataModel)
    """
    surface = build_cp_selection_a2ui(providers, surface_id)
    return generate_a2ui_messages(
        surface_id=surface["surfaceId"],
        components=surface["components"],
        data_model=surface["dataModel"]
    )


# =============================================================================
# Payment Method Selection A2UI Builder
# =============================================================================

def build_payment_method_selection_a2ui(
    payment_methods: list[dict],
    surface_id: Optional[str] = None
) -> dict:
    """
    Build an A2UI surface for payment method selection.

    Args:
        payment_methods: List of payment methods with id, type, brand, last4
        surface_id: Optional surface ID (generated if not provided)

    Returns:
        A2UI surface definition for payment method selection
    """
    surface_id = surface_id or _generate_id("payment-method-selection")

    # Build payment method card components
    method_components = []
    card_ids = []

    for index, method in enumerate(payment_methods):
        card_id = _generate_id(f"pm-card-{index}")
        row_id = _generate_id(f"pm-row-{index}")
        index_id = _generate_id(f"pm-index-{index}")
        info_col_id = _generate_id(f"pm-info-{index}")
        brand_id = _generate_id(f"pm-brand-{index}")
        type_id = _generate_id(f"pm-type-{index}")

        card_ids.append(card_id)

        # Format display text
        brand = method.get("brand", "").upper()
        last4 = method.get("last4", "")
        display_text = f"{brand} **** {last4}" if brand and last4 else method.get("type", "カード")

        type_text = "クレジットカード" if method.get("type") == "card" else method.get("type", "")

        method_components.extend([
            # Card
            {
                "id": card_id,
                "component": {
                    "Card": {
                        "child": row_id,
                        "action": {
                            "name": "select_payment_method",
                            "context": {
                                "index": {"literalNumber": index + 1},
                                "paymentMethodId": {"literalString": method["id"]}
                            }
                        }
                    }
                }
            },
            # Row layout
            {
                "id": row_id,
                "component": {
                    "Row": {
                        "children": [index_id, info_col_id],
                        "alignment": "center",
                        "gap": 12
                    }
                }
            },
            # Index number
            {
                "id": index_id,
                "component": {
                    "Text": {
                        "text": {"literalString": str(index + 1)},
                        "styleHint": "h2"
                    }
                }
            },
            # Info column
            {
                "id": info_col_id,
                "component": {
                    "Column": {
                        "children": [brand_id, type_id],
                        "distribution": "start",
                        "gap": 4
                    }
                }
            },
            # Brand and last4
            {
                "id": brand_id,
                "component": {
                    "Text": {
                        "text": {"literalString": display_text},
                        "styleHint": "h4"
                    }
                }
            },
            # Type
            {
                "id": type_id,
                "component": {
                    "Text": {
                        "text": {"literalString": type_text},
                        "styleHint": "caption"
                    }
                }
            }
        ])

    # Build list container
    # Root component must have id="root" for A2UI v0.9 auto-rendering

    components = [
        {
            "id": "root",
            "component": {
                "Column": {
                    "children": card_ids,
                    "distribution": "start",
                    "gap": 8
                }
            }
        }
    ] + method_components

    # Build data model
    data_model = {
        "paymentMethods": [
            {
                "id": m["id"],
                "type": m.get("type", ""),
                "brand": m.get("brand", ""),
                "last4": m.get("last4", "")
            }
            for m in payment_methods
        ],
        "selectedIndex": None
    }

    return {
        "surfaceId": surface_id,
        "surfaceType": "payment_method_selection",
        "components": components,
        "dataModel": data_model
    }


def generate_payment_method_selection_a2ui_messages(
    payment_methods: list[dict],
    surface_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Generate A2UI v0.9 protocol messages for payment method selection.

    Args:
        payment_methods: List of payment methods
        surface_id: Optional surface ID

    Returns:
        List of SSE events (createSurface, updateComponents, updateDataModel)
    """
    surface = build_payment_method_selection_a2ui(payment_methods, surface_id)
    return generate_a2ui_messages(
        surface_id=surface["surfaceId"],
        components=surface["components"],
        data_model=surface["dataModel"]
    )


# =============================================================================
# Product Carousel A2UI Builder
# =============================================================================

def build_product_carousel_a2ui(
    products: list[dict],
    surface_id: Optional[str] = None
) -> dict:
    """
    Build an A2UI surface for product carousel.

    Args:
        products: List of products with id, sku, name, description, price, inventory_count, image_url
        surface_id: Optional surface ID (generated if not provided)

    Returns:
        A2UI surface definition for product carousel
    """
    surface_id = surface_id or _generate_id("product-carousel")

    # Build product card components
    product_components = []
    card_ids = []

    for index, product in enumerate(products):
        card_id = _generate_id(f"product-card-{index}")
        col_id = _generate_id(f"product-col-{index}")
        image_id = _generate_id(f"product-image-{index}")
        name_id = _generate_id(f"product-name-{index}")
        desc_id = _generate_id(f"product-desc-{index}")
        price_id = _generate_id(f"product-price-{index}")
        inventory_id = _generate_id(f"product-inventory-{index}")
        button_text_id = _generate_id(f"button-text-{index}")
        button_id = _generate_id(f"add-to-cart-{index}")

        card_ids.append(card_id)

        # Format price (cents to yen)
        price = product.get("price", 0)
        price_text = f"¥{price // 100:,}" if isinstance(price, int) else f"¥{price:,.0f}"

        # Get image URL
        image_url = product.get("metadata", {}).get("image_url") or product.get("image_url") or "https://placehold.co/400x400/EEE/999?text=No+Image"

        # Inventory count
        inventory_count = product.get("inventory_count", 0)

        product_components.extend([
            # Card
            {
                "id": card_id,
                "component": {
                    "Card": {
                        "child": col_id
                    }
                }
            },
            # Column layout
            {
                "id": col_id,
                "component": {
                    "Column": {
                        "children": [image_id, name_id, desc_id, price_id, inventory_id, button_id],
                        "distribution": "start",
                        "gap": 8
                    }
                }
            },
            # Product image
            {
                "id": image_id,
                "component": {
                    "Image": {
                        "url": {"literalString": image_url},
                        "fit": "contain",
                        "usageHint": "thumbnail",
                        "altText": {"literalString": product.get("name", "")}
                    }
                }
            },
            # Product name
            {
                "id": name_id,
                "component": {
                    "Text": {
                        "text": {"literalString": product.get("name", "")},
                        "styleHint": "h4"
                    }
                }
            },
            # Description
            {
                "id": desc_id,
                "component": {
                    "Text": {
                        "text": {"literalString": product.get("description", "")[:100]},
                        "styleHint": "caption"
                    }
                }
            },
            # Price
            {
                "id": price_id,
                "component": {
                    "Text": {
                        "text": {"literalString": price_text},
                        "styleHint": "h3"
                    }
                }
            },
            # Inventory
            {
                "id": inventory_id,
                "component": {
                    "Text": {
                        "text": {"literalString": f"在庫: {inventory_count}点"},
                        "styleHint": "caption"
                    }
                }
            },
            # Button text
            {
                "id": button_text_id,
                "component": {
                    "Text": {
                        "text": {"literalString": "カートに追加"}
                    }
                }
            },
            # Add to cart button
            {
                "id": button_id,
                "component": {
                    "Button": {
                        "child": button_text_id,
                        "primary": True,
                        "disabled": {"literalBoolean": inventory_count == 0},
                        "action": {
                            "name": "add_to_cart",
                            "context": {
                                "productId": {"literalString": product.get("id", "")},
                                "sku": {"literalString": product.get("sku", "")}
                            }
                        }
                    }
                }
            }
        ])

    # Build horizontal list container
    # Root component must have id="root" for A2UI v0.9 auto-rendering

    components = [
        {
            "id": "root",
            "component": {
                "List": {
                    "children": card_ids,
                    "dataPath": "/products",
                    "direction": "horizontal",
                    "gap": 16
                }
            }
        }
    ] + product_components

    # Build data model
    data_model = {
        "products": [
            {
                "id": p.get("id", ""),
                "sku": p.get("sku", ""),
                "name": p.get("name", ""),
                "description": p.get("description", ""),
                "price": p.get("price", 0),
                "inventory_count": p.get("inventory_count", 0),
                "image_url": p.get("metadata", {}).get("image_url") or p.get("image_url") or ""
            }
            for p in products
        ]
    }

    return {
        "surfaceId": surface_id,
        "surfaceType": "product_carousel",
        "components": components,
        "dataModel": data_model
    }


def generate_product_carousel_a2ui_messages(
    products: list[dict],
    surface_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Generate A2UI v0.9 protocol messages for product carousel.

    Args:
        products: List of products
        surface_id: Optional surface ID

    Returns:
        List of SSE events (createSurface, updateComponents, updateDataModel)
    """
    surface = build_product_carousel_a2ui(products, surface_id)
    return generate_a2ui_messages(
        surface_id=surface["surfaceId"],
        components=surface["components"],
        data_model=surface["dataModel"]
    )


# =============================================================================
# Cart Details Modal A2UI Builder
# =============================================================================

def build_cart_details_a2ui(
    cart_candidate: dict,
    surface_id: Optional[str] = None
) -> dict:
    """
    Build an A2UI surface for cart details modal.

    Args:
        cart_candidate: Cart candidate with artifact_id, artifact_name, cart_mandate
        surface_id: Optional surface ID (generated if not provided)

    Returns:
        A2UI surface definition for cart details modal
    """
    surface_id = surface_id or _generate_id("cart-details")

    cart_mandate = cart_candidate.get("cart_mandate", {})
    contents = cart_mandate.get("contents", {})
    metadata = cart_mandate.get("_metadata", {})
    payment_request = contents.get("payment_request", {})
    details = payment_request.get("details", {})

    cart_name = metadata.get("cart_name") or cart_candidate.get("artifact_name") or "カート"
    cart_description = metadata.get("cart_description", "")
    merchant_name = contents.get("merchant_name", "")

    display_items = details.get("display_items", [])
    total = details.get("total", {})
    shipping_address = payment_request.get("shipping_address", {})
    shipping_options = details.get("shipping_options", [])

    # Categorize items
    product_items = [item for item in display_items if item.get("refund_period", 0) > 0]
    shipping_item = next((item for item in display_items if "送料" in item.get("label", "")), None)
    tax_item = next((item for item in display_items if "税" in item.get("label", "")), None)

    # Calculate subtotal
    subtotal = sum(item.get("amount", {}).get("value", 0) for item in product_items)

    # Build components
    components = []

    # Modal content column
    content_col_id = _generate_id("cart-content-col")

    # Header
    header_row_id = _generate_id("cart-header")
    header_icon_id = _generate_id("cart-icon")
    header_title_id = _generate_id("cart-title")
    header_desc_id = _generate_id("cart-desc")

    components.extend([
        {
            "id": header_row_id,
            "component": {
                "Row": {
                    "children": [header_icon_id, header_title_id],
                    "alignment": "center",
                    "gap": 8
                }
            }
        },
        {
            "id": header_icon_id,
            "component": {
                "Icon": {
                    "name": "package"
                }
            }
        },
        {
            "id": header_title_id,
            "component": {
                "Text": {
                    "text": {"literalString": cart_name},
                    "styleHint": "h2"
                }
            }
        }
    ])

    if cart_description:
        components.append({
            "id": header_desc_id,
            "component": {
                "Text": {
                    "text": {"literalString": cart_description},
                    "styleHint": "body"
                }
            }
        })

    # Product list section
    products_section_id = _generate_id("products-section")
    products_header_id = _generate_id("products-header")
    products_list_id = _generate_id("products-list")

    product_card_ids = []
    raw_items = metadata.get("raw_items", [])

    for idx, item in enumerate(product_items):
        item_card_id = _generate_id(f"item-card-{idx}")
        item_row_id = _generate_id(f"item-row-{idx}")
        item_info_col_id = _generate_id(f"item-info-{idx}")
        item_name_id = _generate_id(f"item-name-{idx}")
        item_price_id = _generate_id(f"item-price-{idx}")

        product_card_ids.append(item_card_id)

        raw_item = raw_items[idx] if idx < len(raw_items) else {}
        unit_price = raw_item.get("unit_price", {}).get("value", 0)
        quantity = raw_item.get("quantity", 1)

        components.extend([
            {
                "id": item_card_id,
                "component": {
                    "Card": {
                        "child": item_row_id
                    }
                }
            },
            {
                "id": item_row_id,
                "component": {
                    "Row": {
                        "children": [item_info_col_id, item_price_id],
                        "alignment": "center",
                        "distribution": "spaceBetween"
                    }
                }
            },
            {
                "id": item_info_col_id,
                "component": {
                    "Column": {
                        "children": [item_name_id],
                        "distribution": "start"
                    }
                }
            },
            {
                "id": item_name_id,
                "component": {
                    "Text": {
                        "text": {"literalString": item.get("label", "")},
                        "styleHint": "h4"
                    }
                }
            },
            {
                "id": item_price_id,
                "component": {
                    "Text": {
                        "text": {"literalString": f"¥{item.get('amount', {}).get('value', 0):,}"},
                        "styleHint": "h4"
                    }
                }
            }
        ])

    components.extend([
        {
            "id": products_header_id,
            "component": {
                "Text": {
                    "text": {"literalString": f"商品一覧（{len(product_items)}点）"},
                    "styleHint": "h4"
                }
            }
        },
        {
            "id": products_list_id,
            "component": {
                "Column": {
                    "children": product_card_ids,
                    "distribution": "start",
                    "gap": 8
                }
            }
        }
    ])

    # Divider
    divider1_id = _generate_id("divider1")
    components.append({
        "id": divider1_id,
        "component": {
            "Divider": {
                "orientation": "horizontal"
            }
        }
    })

    # Price breakdown
    price_section_id = _generate_id("price-section")
    subtotal_row_id = _generate_id("subtotal-row")
    subtotal_label_id = _generate_id("subtotal-label")
    subtotal_value_id = _generate_id("subtotal-value")
    total_row_id = _generate_id("total-row")
    total_label_id = _generate_id("total-label")
    total_value_id = _generate_id("total-value")

    price_children = [subtotal_row_id]

    components.extend([
        {
            "id": subtotal_row_id,
            "component": {
                "Row": {
                    "children": [subtotal_label_id, subtotal_value_id],
                    "distribution": "spaceBetween"
                }
            }
        },
        {
            "id": subtotal_label_id,
            "component": {
                "Text": {
                    "text": {"literalString": "小計"},
                    "styleHint": "body"
                }
            }
        },
        {
            "id": subtotal_value_id,
            "component": {
                "Text": {
                    "text": {"literalString": f"¥{subtotal:,}"},
                    "styleHint": "body"
                }
            }
        }
    ])

    # Tax row if exists
    if tax_item:
        tax_row_id = _generate_id("tax-row")
        tax_label_id = _generate_id("tax-label")
        tax_value_id = _generate_id("tax-value")
        price_children.append(tax_row_id)

        components.extend([
            {
                "id": tax_row_id,
                "component": {
                    "Row": {
                        "children": [tax_label_id, tax_value_id],
                        "distribution": "spaceBetween"
                    }
                }
            },
            {
                "id": tax_label_id,
                "component": {
                    "Text": {
                        "text": {"literalString": tax_item.get("label", "税")},
                        "styleHint": "body"
                    }
                }
            },
            {
                "id": tax_value_id,
                "component": {
                    "Text": {
                        "text": {"literalString": f"¥{tax_item.get('amount', {}).get('value', 0):,}"},
                        "styleHint": "body"
                    }
                }
            }
        ])

    # Shipping row if exists
    if shipping_item:
        shipping_row_id = _generate_id("shipping-row")
        shipping_label_id = _generate_id("shipping-label")
        shipping_value_id = _generate_id("shipping-value")
        price_children.append(shipping_row_id)

        components.extend([
            {
                "id": shipping_row_id,
                "component": {
                    "Row": {
                        "children": [shipping_label_id, shipping_value_id],
                        "distribution": "spaceBetween"
                    }
                }
            },
            {
                "id": shipping_label_id,
                "component": {
                    "Text": {
                        "text": {"literalString": shipping_item.get("label", "送料")},
                        "styleHint": "body"
                    }
                }
            },
            {
                "id": shipping_value_id,
                "component": {
                    "Text": {
                        "text": {"literalString": f"¥{shipping_item.get('amount', {}).get('value', 0):,}"},
                        "styleHint": "body"
                    }
                }
            }
        ])

    # Total row
    divider2_id = _generate_id("divider2")
    price_children.extend([divider2_id, total_row_id])

    components.extend([
        {
            "id": divider2_id,
            "component": {
                "Divider": {
                    "orientation": "horizontal"
                }
            }
        },
        {
            "id": total_row_id,
            "component": {
                "Row": {
                    "children": [total_label_id, total_value_id],
                    "distribution": "spaceBetween"
                }
            }
        },
        {
            "id": total_label_id,
            "component": {
                "Text": {
                    "text": {"literalString": "合計"},
                    "styleHint": "h3"
                }
            }
        },
        {
            "id": total_value_id,
            "component": {
                "Text": {
                    "text": {"literalString": f"¥{total.get('amount', {}).get('value', 0):,}"},
                    "styleHint": "h3"
                }
            }
        }
    ])

    components.append({
        "id": price_section_id,
        "component": {
            "Column": {
                "children": price_children,
                "distribution": "start",
                "gap": 8
            }
        }
    })

    # Action buttons
    actions_row_id = _generate_id("actions-row")
    close_button_id = _generate_id("close-button")
    close_text_id = _generate_id("close-text")
    select_button_id = _generate_id("select-button")
    select_text_id = _generate_id("select-text")

    components.extend([
        {
            "id": actions_row_id,
            "component": {
                "Row": {
                    "children": [close_button_id, select_button_id],
                    "distribution": "spaceBetween",
                    "gap": 8
                }
            }
        },
        {
            "id": close_text_id,
            "component": {
                "Text": {
                    "text": {"literalString": "閉じる"}
                }
            }
        },
        {
            "id": close_button_id,
            "component": {
                "Button": {
                    "child": close_text_id,
                    "primary": False,
                    "action": {
                        "name": "close_cart_modal"
                    }
                }
            }
        },
        {
            "id": select_text_id,
            "component": {
                "Text": {
                    "text": {"literalString": "このカートを選択"}
                }
            }
        },
        {
            "id": select_button_id,
            "component": {
                "Button": {
                    "child": select_text_id,
                    "primary": True,
                    "action": {
                        "name": "select_cart",
                        "context": {
                            "artifactId": {"literalString": cart_candidate.get("artifact_id", "")}
                        }
                    }
                }
            }
        }
    ])

    # Main content column
    content_children = [header_row_id]
    if cart_description:
        content_children.append(header_desc_id)
    content_children.extend([
        products_header_id,
        products_list_id,
        divider1_id,
        price_section_id,
        actions_row_id
    ])

    components.append({
        "id": content_col_id,
        "component": {
            "Column": {
                "children": content_children,
                "distribution": "start",
                "gap": 16
            }
        }
    })

    # Modal wrapper
    # Root component must have id="root" for A2UI v0.9 auto-rendering
    components.append({
        "id": "root",
        "component": {
            "Modal": {
                "contentChild": content_col_id,
                "open": {"path": "/modalOpen"},
                "title": {"literalString": cart_name}
            }
        }
    })

    # Build data model
    data_model = {
        "cart": {
            "id": contents.get("id", ""),
            "name": cart_name,
            "description": cart_description,
            "merchant_name": merchant_name,
            "items": [
                {
                    "label": item.get("label", ""),
                    "description": raw_items[idx].get("description", "") if idx < len(raw_items) else "",
                    "image_url": raw_items[idx].get("image_url", "") if idx < len(raw_items) else "",
                    "unit_price": raw_items[idx].get("unit_price", {}).get("value", 0) if idx < len(raw_items) else 0,
                    "quantity": raw_items[idx].get("quantity", 1) if idx < len(raw_items) else 1,
                    "total_price": item.get("amount", {}).get("value", 0)
                }
                for idx, item in enumerate(product_items)
            ],
            "subtotal": subtotal,
            "tax": tax_item.get("amount", {}).get("value", 0) if tax_item else 0,
            "shipping": shipping_item.get("amount", {}).get("value", 0) if shipping_item else 0,
            "total": total.get("amount", {}).get("value", 0)
        },
        "modalOpen": False  # デフォルトは閉じた状態。ユーザーが「詳細」をクリックしたときに開く
    }

    if shipping_address:
        data_model["cart"]["shipping_address"] = {
            "recipient": shipping_address.get("recipient", ""),
            "postal_code": shipping_address.get("postal_code", ""),
            "city": shipping_address.get("city", ""),
            "region": shipping_address.get("region", ""),
            "address_line": shipping_address.get("address_line", []),
            "phone_number": shipping_address.get("phone_number", "")
        }

    return {
        "surfaceId": surface_id,
        "surfaceType": "cart_details",
        "components": components,
        "dataModel": data_model
    }


def generate_cart_details_a2ui_messages(
    cart_candidate: dict,
    surface_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Generate A2UI v0.9 protocol messages for cart details modal.

    Args:
        cart_candidate: Cart candidate data
        surface_id: Optional surface ID

    Returns:
        List of SSE events (createSurface, updateComponents, updateDataModel)
    """
    surface = build_cart_details_a2ui(cart_candidate, surface_id)
    return generate_a2ui_messages(
        surface_id=surface["surfaceId"],
        components=surface["components"],
        data_model=surface["dataModel"]
    )
