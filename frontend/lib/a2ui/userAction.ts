/**
 * A2UI v0.9 Client-to-Server Message Builder
 *
 * Implements the userAction message format for sending user interactions
 * from the client to the server.
 *
 * @see https://github.com/google/A2UI/blob/main/specification/0.9/json/client_to_server.json
 */

/**
 * A2UI v0.9 UserAction message structure
 */
export interface A2UIUserAction {
  userAction: {
    name: string;
    surfaceId: string;
    sourceComponentId: string;
    timestamp: string;
    context?: Record<string, any>;
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
 * @param name - The action name (e.g., "submit_shipping", "select_payment_method")
 * @param surfaceId - The surface ID where the action originated
 * @param sourceComponentId - The component ID that triggered the action
 * @param context - Optional context data (resolved data bindings)
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
      ...(context && { context }),
    },
  };
}

/**
 * Build an error message for A2UI v0.9
 *
 * @param code - Error code (e.g., "VALIDATION_FAILED")
 * @param surfaceId - The surface ID where the error occurred
 * @param message - Human-readable error message
 * @param path - Optional JSON Pointer path to the error location
 * @returns A2UI v0.9 compliant error message
 */
export function buildClientError(
  code: string,
  surfaceId: string,
  message: string,
  path?: string
): A2UIClientError {
  return {
    error: {
      code,
      surfaceId,
      message,
      ...(path && { path }),
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
