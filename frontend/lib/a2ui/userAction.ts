/**
 * A2UI v0.9 Client-to-Server Message Builder
 *
 * Implements the userAction message format for sending user interactions
 * from the client to the server.
 *
 * A2UI Philosophy:
 * - userAction.context contains PATH REFERENCES only (e.g., { "path": "/shipping" })
 * - Actual data lives in the DataModel, sent alongside userAction
 * - Backend resolves paths from context against the DataModel
 *
 * @see https://github.com/google/A2UI/blob/main/specification/0.9/json/client_to_server.json
 */

/**
 * Path reference for A2UI context
 * Context values should be path references, not actual data
 */
export interface PathReference {
  path: string;
}

/**
 * A2UI v0.9 UserAction message structure
 */
export interface A2UIUserAction {
  userAction: {
    name: string;
    surfaceId: string;
    sourceComponentId: string;
    timestamp: string;
    context?: Record<string, PathReference>;  // Only path references
  };
}

/**
 * Complete A2UI client-to-server message with DataModel
 * userAction + dataModel are sent together
 */
export interface A2UIClientMessage {
  userAction: A2UIUserAction["userAction"];
  dataModel: Record<string, any>;  // Current DataModel state
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
 * A2UI Philosophy: context contains PATH REFERENCES only, not actual data.
 * Example: { shipping: { path: "/shipping" } }
 *
 * @param name - The action name (e.g., "submit_shipping", "select_payment_method")
 * @param surfaceId - The surface ID where the action originated
 * @param sourceComponentId - The component ID that triggered the action
 * @param contextPaths - Path references (e.g., { shipping: "/shipping" })
 * @returns A2UI v0.9 compliant userAction message
 */
export function buildUserAction(
  name: string,
  surfaceId: string,
  sourceComponentId: string,
  contextPaths?: Record<string, string>  // key -> path string
): A2UIUserAction {
  // Convert path strings to PathReference objects
  const context = contextPaths
    ? Object.fromEntries(
        Object.entries(contextPaths).map(([key, path]) => [key, { path }])
      )
    : undefined;

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
 * Build a complete A2UI client message with userAction and DataModel
 *
 * This is the pure A2UI approach:
 * - userAction.context has path references only
 * - dataModel contains the actual data
 * - Backend resolves paths against dataModel
 *
 * @param name - The action name
 * @param surfaceId - The surface ID
 * @param sourceComponentId - The component ID
 * @param contextPaths - Path references for context
 * @param dataModel - Current DataModel state
 * @returns Complete A2UI client message
 */
export function buildClientMessage(
  name: string,
  surfaceId: string,
  sourceComponentId: string,
  contextPaths: Record<string, string>,
  dataModel: Record<string, any>
): A2UIClientMessage {
  const userAction = buildUserAction(name, surfaceId, sourceComponentId, contextPaths);
  return {
    userAction: userAction.userAction,
    dataModel,
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
 * Serialize a complete client message (userAction + dataModel) to JSON string
 */
export function serializeClientMessage(message: A2UIClientMessage): string {
  return JSON.stringify(message);
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
