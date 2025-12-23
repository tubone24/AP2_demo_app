"""
A2UI v0.9 Client-to-Server Message Parser

Parses userAction messages from the frontend and extracts
action name, context paths, and resolves data from DataModel.

A2UI Philosophy:
- userAction.context contains PATH REFERENCES only
- Actual data lives in the dataModel
- Backend resolves paths against dataModel

@see https://github.com/google/A2UI/blob/main/specification/0.9/json/client_to_server.json
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class A2UIUserAction:
    """Parsed A2UI v0.9 userAction message with resolved data"""

    def __init__(
        self,
        name: str,
        surface_id: str,
        source_component_id: str,
        timestamp: str,
        context_paths: Optional[Dict[str, str]] = None,
        resolved_data: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.surface_id = surface_id
        self.source_component_id = source_component_id
        self.timestamp = timestamp
        self.context_paths = context_paths or {}
        self.resolved_data = resolved_data or {}

    def __repr__(self) -> str:
        return f"A2UIUserAction(name={self.name}, surface_id={self.surface_id}, resolved_data={self.resolved_data})"


def is_a2ui_message(user_input: str) -> bool:
    """
    Check if the user input is an A2UI message.

    Detects by checking if the input is valid JSON with a "userAction" key.
    """
    try:
        data = json.loads(user_input)
        return isinstance(data, dict) and "userAction" in data
    except (json.JSONDecodeError, TypeError):
        return False


def _resolve_path(path: str, data_model: Dict[str, Any]) -> Any:
    """
    Resolve a JSON Pointer path against a data model.

    Args:
        path: JSON Pointer path (e.g., "/shipping" or "/selection")
        data_model: The data model to resolve against

    Returns:
        The value at the path, or None if not found
    """
    if not path or path == "/":
        return data_model

    # Remove leading slash and split by /
    parts = path.lstrip("/").split("/")

    current = data_model
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index]
            except (ValueError, IndexError):
                return None
        else:
            return None

    return current


def parse_a2ui_message(user_input: str) -> Optional[A2UIUserAction]:
    """
    Parse an A2UI client message (userAction + dataModel).

    Expected format:
    {
      "userAction": {
        "name": "submit_shipping",
        "surfaceId": "...",
        "sourceComponentId": "...",
        "timestamp": "...",
        "context": {
          "shipping": { "path": "/shipping" }
        }
      },
      "dataModel": {
        "shipping": { "recipient": "...", ... }
      }
    }

    Returns:
        A2UIUserAction with resolved data from dataModel
    """
    try:
        data = json.loads(user_input)

        if not isinstance(data, dict) or "userAction" not in data:
            return None

        action = data["userAction"]
        data_model = data.get("dataModel", {})

        # Extract required fields
        name = action.get("name")
        surface_id = action.get("surfaceId", "")
        source_component_id = action.get("sourceComponentId", "")
        timestamp = action.get("timestamp", "")
        context = action.get("context", {})

        if not name:
            logger.warning("[A2UI] userAction missing 'name' field")
            return None

        # Resolve paths from context against dataModel
        context_paths = {}
        resolved_data = {}

        for key, value in context.items():
            if isinstance(value, dict) and "path" in value:
                path = value["path"]
                context_paths[key] = path
                # Resolve the path against dataModel
                resolved_value = _resolve_path(path, data_model)
                if resolved_value is not None:
                    resolved_data[key] = resolved_value
                    logger.debug(f"[A2UI] Resolved {path} -> {resolved_value}")
                else:
                    logger.warning(f"[A2UI] Path '{path}' not found in dataModel")

        return A2UIUserAction(
            name=name,
            surface_id=surface_id,
            source_component_id=source_component_id,
            timestamp=timestamp,
            context_paths=context_paths,
            resolved_data=resolved_data
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
    - Resolves path references from context against dataModel
    - Converts to node-compatible format

    For regular text messages:
    - Returns the original input as-is

    Returns:
        Tuple of (processed_input_for_nodes, parsed_action_or_none)
    """
    action = parse_a2ui_message(user_input)

    if action:
        logger.info(f"[A2UI v0.9] Received userAction: {action.name}")
        logger.debug(f"[A2UI v0.9] Resolved data: {action.resolved_data}")

        # Convert action to node-compatible format
        processed_input = _convert_action_to_node_input(action)
        return processed_input, action
    else:
        # Not an A2UI message, return as-is
        return user_input, None


def _convert_action_to_node_input(action: A2UIUserAction) -> str:
    """
    Convert A2UI userAction to node-compatible input format.

    Uses resolved_data (values from dataModel resolved via path references).
    """
    name = action.name
    resolved = action.resolved_data

    if name == "submit_shipping":
        # Shipping form: nodes expect JSON string of shipping data
        shipping = resolved.get("shipping", {})
        return json.dumps(shipping)

    elif name == "select_credential_provider":
        # CP selection: nodes expect index number as string
        selection = resolved.get("selection", {})
        index = selection.get("index", 1)
        return str(index)

    elif name == "select_payment_method":
        # Payment method selection: nodes expect index number as string
        selection = resolved.get("selection", {})
        index = selection.get("index", 1)
        return str(index)

    elif name == "add_to_cart":
        # Add to cart: nodes expect product identifier
        selection = resolved.get("selection", {})
        product_id = selection.get("productId", "")
        sku = selection.get("sku", "")
        return f"add {sku or product_id}"

    elif name == "select_cart":
        # Cart selection: nodes expect cart identifier
        selection = resolved.get("selection", {})
        artifact_id = selection.get("artifactId", "")
        return f"select cart {artifact_id}"

    elif name == "close_cart_modal":
        return "close"

    else:
        # Unknown action - return action name as fallback
        logger.warning(f"[A2UI] Unknown action: {name}, using name as input")
        return name
