"""
A2UI v0.9 Client-to-Server Message Parser

Parses userAction messages from the frontend and extracts
action name, context, and other relevant information.

@see https://github.com/google/A2UI/blob/main/specification/0.9/json/client_to_server.json
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class A2UIUserAction:
    """Parsed A2UI v0.9 userAction message"""

    def __init__(
        self,
        name: str,
        surface_id: str,
        source_component_id: str,
        timestamp: str,
        context: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.surface_id = surface_id
        self.source_component_id = source_component_id
        self.timestamp = timestamp
        self.context = context or {}

    def __repr__(self) -> str:
        return f"A2UIUserAction(name={self.name}, surface_id={self.surface_id}, context={self.context})"


def is_a2ui_message(user_input: str) -> bool:
    """
    Check if the user input is an A2UI userAction message.

    Detects by checking if the input is valid JSON with a "userAction" key.
    """
    try:
        data = json.loads(user_input)
        return isinstance(data, dict) and "userAction" in data
    except (json.JSONDecodeError, TypeError):
        return False


def parse_a2ui_message(user_input: str) -> Optional[A2UIUserAction]:
    """
    Parse an A2UI userAction message from user input.

    Expected format: {"userAction": {...}}

    Returns:
        A2UIUserAction object if parsing succeeds, None otherwise
    """
    try:
        data = json.loads(user_input)

        if not isinstance(data, dict) or "userAction" not in data:
            return None

        action = data["userAction"]

        # Extract required fields
        name = action.get("name")
        surface_id = action.get("surfaceId", "")
        source_component_id = action.get("sourceComponentId", "")
        timestamp = action.get("timestamp", "")
        context = action.get("context")

        if not name:
            logger.warning("[A2UI] userAction missing 'name' field")
            return None

        return A2UIUserAction(
            name=name,
            surface_id=surface_id,
            source_component_id=source_component_id,
            timestamp=timestamp,
            context=context
        )

    except json.JSONDecodeError as e:
        logger.debug(f"[A2UI] Not a JSON message: {e}")
        return None
    except Exception as e:
        logger.error(f"[A2UI] Unexpected error parsing message: {e}")
        return None


def process_user_input(user_input: str) -> Tuple[str, Optional[A2UIUserAction]]:
    """
    Process user input and return both the processed input and parsed action (if any).

    For A2UI userAction messages:
    - Extracts the action context and converts to appropriate format for nodes
    - Returns the action object for additional processing

    For regular text messages:
    - Returns the original input as-is

    Returns:
        Tuple of (processed_input_for_nodes, parsed_action_or_none)
    """
    action = parse_a2ui_message(user_input)

    if action:
        logger.info(f"[A2UI v0.9] Received userAction: {action.name}")
        logger.debug(f"[A2UI v0.9] Context: {action.context}")

        # Convert action to node-compatible format based on action name
        processed_input = _convert_action_to_node_input(action)
        return processed_input, action
    else:
        # Not an A2UI message, return as-is
        return user_input, None


def _convert_action_to_node_input(action: A2UIUserAction) -> str:
    """
    Convert A2UI userAction to node-compatible input format.

    Each action type has its own conversion logic based on what
    the LangGraph nodes expect.
    """
    name = action.name
    context = action.context or {}

    if name == "submit_shipping":
        # Shipping form: nodes expect JSON string of shipping data
        shipping = context.get("shipping", {})
        return json.dumps(shipping)

    elif name == "select_credential_provider":
        # CP selection: nodes expect index number as string
        index = context.get("index", 1)
        return str(index)

    elif name == "select_payment_method":
        # Payment method selection: nodes expect index number as string
        index = context.get("index", 1)
        return str(index)

    elif name == "add_to_cart":
        # Add to cart: nodes expect product identifier
        product_id = context.get("productId", "")
        sku = context.get("sku", "")
        return f"add {sku or product_id}"

    elif name == "select_cart":
        # Cart selection: nodes expect cart identifier
        artifact_id = context.get("artifactId", "")
        return f"select cart {artifact_id}"

    elif name == "close_cart_modal":
        return "close"

    else:
        # Unknown action - return action name as fallback
        logger.warning(f"[A2UI] Unknown action: {name}, using name as input")
        return name
