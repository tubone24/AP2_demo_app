/**
 * A2UI v0.9 Client-to-Server Message Builder
 *
 * Implements the userAction message format for sending user interactions
 * from the client to the server.
 *
 * A2UI v0.9 Specification:
 * - userAction.context contains RESOLVED VALUES (not path references)
 * - Client resolves paths and literal values before sending
 * - Server receives ready-to-use values
 *
 * @see https://a2ui.org/specification/v0.9-a2ui/
 */

/**
 * A2UI v0.9 UserAction message structure
 * context contains resolved values (strings, numbers, booleans, objects)
 */
export interface A2UIUserAction {
  userAction: {
    name: string;
    surfaceId: string;
    sourceComponentId: string;
    timestamp: string;
    context?: Record<string, any>;  // Resolved values
  };
}

/**
 * A2UI v0.9 Error message structure
 */
export interface A2UIClientError {
  error: {
    code: string;
    surfaceId: string;
    message: string;
    path?: string;
  };
}

/**
 * Build a userAction message for A2UI v0.9
 *
 * A2UI v0.9: context contains RESOLVED values.
 * - Path references are resolved against dataModel
 * - Literal values are extracted from their wrappers
 *
 * @param name - The action name (e.g., "submit_shipping", "select_credential_provider")
 * @param surfaceId - The surface ID where the action originated
 * @param sourceComponentId - The component ID that triggered the action
 * @param context - Resolved context values
 * @returns A2UI v0.9 compliant userAction message
 */
export function buildUserAction(
  name: string,
  surfaceId: string,
  sourceComponentId: string,
  context?: Record<string, any>
): A2UIUserAction {
  return {
    userAction: {
      name,
      surfaceId,
      sourceComponentId,
      timestamp: new Date().toISOString(),
      ...(context && Object.keys(context).length > 0 && { context }),
    },
  };
}

/**
 * Serialize a userAction message to JSON string for sending
 */
export function serializeUserAction(action: A2UIUserAction): string {
  return JSON.stringify(action);
}

/**
 * Check if a message string is a userAction message
 * Detects by checking if the JSON has a "userAction" key
 */
export function isUserActionMessage(message: string): boolean {
  try {
    const parsed = JSON.parse(message);
    return typeof parsed === "object" && parsed !== null && "userAction" in parsed;
  } catch {
    // Not valid JSON, not a userAction message
    return false;
  }
}

/**
 * Parse a userAction message from JSON string
 */
export function parseUserAction(message: string): A2UIUserAction | null {
  try {
    const parsed = JSON.parse(message);
    if (typeof parsed === "object" && parsed !== null && "userAction" in parsed) {
      return parsed as A2UIUserAction;
    }
    return null;
  } catch {
    return null;
  }
}
