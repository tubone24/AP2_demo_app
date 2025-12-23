/**
 * JSON Pointer (RFC 6901) Implementation for A2UI v0.9
 *
 * Supports:
 * - Path parsing and navigation
 * - add, replace, remove operations (similar to JSON Patch RFC 6902)
 *
 * @see https://datatracker.ietf.org/doc/html/rfc6901
 * @see https://a2ui.org/specification/v0.9-a2ui/
 */

/**
 * Parse a JSON Pointer string into path segments
 * @param pointer - JSON Pointer string (e.g., "/shipping/city" or "/items/0")
 * @returns Array of path segments
 */
export function parseJsonPointer(pointer: string): string[] {
  if (pointer === "" || pointer === "/") {
    return [];
  }

  if (!pointer.startsWith("/")) {
    throw new Error(`Invalid JSON Pointer: must start with "/" or be empty. Got: ${pointer}`);
  }

  // Split by "/" and decode escaped characters
  // RFC 6901: ~1 = /, ~0 = ~
  return pointer
    .slice(1) // Remove leading "/"
    .split("/")
    .map((segment) => segment.replace(/~1/g, "/").replace(/~0/g, "~"));
}

/**
 * Get value at a JSON Pointer path
 * @param obj - The object to traverse
 * @param pointer - JSON Pointer string
 * @returns The value at the path, or undefined if not found
 */
export function getByPointer<T = any>(obj: Record<string, any>, pointer: string): T | undefined {
  const segments = parseJsonPointer(pointer);

  let current: any = obj;
  for (const segment of segments) {
    if (current === null || current === undefined) {
      return undefined;
    }
    if (Array.isArray(current)) {
      const index = parseInt(segment, 10);
      if (isNaN(index)) {
        return undefined;
      }
      current = current[index];
    } else if (typeof current === "object") {
      current = current[segment];
    } else {
      return undefined;
    }
  }

  return current as T;
}

/**
 * Set value at a JSON Pointer path (immutable - returns new object)
 * @param obj - The object to modify
 * @param pointer - JSON Pointer string
 * @param value - The value to set
 * @returns A new object with the value set
 */
export function setByPointer<T extends Record<string, any>>(
  obj: T,
  pointer: string,
  value: any
): T {
  const segments = parseJsonPointer(pointer);

  if (segments.length === 0) {
    // Root replacement
    return value as T;
  }

  // Deep clone the object
  const result = deepClone(obj);

  let current: any = result;
  for (let i = 0; i < segments.length - 1; i++) {
    const segment = segments[i];
    const nextSegment = segments[i + 1];

    if (Array.isArray(current)) {
      const index = parseInt(segment, 10);
      if (current[index] === undefined || current[index] === null) {
        // Create intermediate object or array based on next segment
        current[index] = isArrayIndex(nextSegment) ? [] : {};
      } else {
        // Clone existing value
        current[index] = deepClone(current[index]);
      }
      current = current[index];
    } else {
      if (current[segment] === undefined || current[segment] === null) {
        // Create intermediate object or array based on next segment
        current[segment] = isArrayIndex(nextSegment) ? [] : {};
      } else {
        // Clone existing value
        current[segment] = deepClone(current[segment]);
      }
      current = current[segment];
    }
  }

  // Set the final value
  const lastSegment = segments[segments.length - 1];
  if (Array.isArray(current)) {
    const index = parseInt(lastSegment, 10);
    current[index] = value;
  } else {
    current[lastSegment] = value;
  }

  return result;
}

/**
 * Remove value at a JSON Pointer path (immutable - returns new object)
 * @param obj - The object to modify
 * @param pointer - JSON Pointer string
 * @returns A new object with the value removed
 */
export function removeByPointer<T extends Record<string, any>>(
  obj: T,
  pointer: string
): T {
  const segments = parseJsonPointer(pointer);

  if (segments.length === 0) {
    // Cannot remove root
    return {} as T;
  }

  // Deep clone the object
  const result = deepClone(obj);

  let current: any = result;
  for (let i = 0; i < segments.length - 1; i++) {
    const segment = segments[i];
    if (Array.isArray(current)) {
      const index = parseInt(segment, 10);
      if (current[index] === undefined) {
        return result; // Path doesn't exist, return unchanged
      }
      current[index] = deepClone(current[index]);
      current = current[index];
    } else {
      if (current[segment] === undefined) {
        return result; // Path doesn't exist, return unchanged
      }
      current[segment] = deepClone(current[segment]);
      current = current[segment];
    }
  }

  // Remove the final value
  const lastSegment = segments[segments.length - 1];
  if (Array.isArray(current)) {
    const index = parseInt(lastSegment, 10);
    current.splice(index, 1);
  } else {
    delete current[lastSegment];
  }

  return result;
}

/**
 * Add value at a JSON Pointer path (immutable - returns new object)
 * For arrays, this inserts at the specified index
 * For objects, this is equivalent to set
 * @param obj - The object to modify
 * @param pointer - JSON Pointer string
 * @param value - The value to add
 * @returns A new object with the value added
 */
export function addByPointer<T extends Record<string, any>>(
  obj: T,
  pointer: string,
  value: any
): T {
  const segments = parseJsonPointer(pointer);

  if (segments.length === 0) {
    // Root replacement
    return value as T;
  }

  // Deep clone the object
  const result = deepClone(obj);

  let current: any = result;
  for (let i = 0; i < segments.length - 1; i++) {
    const segment = segments[i];
    const nextSegment = segments[i + 1];

    if (Array.isArray(current)) {
      const index = parseInt(segment, 10);
      if (current[index] === undefined || current[index] === null) {
        current[index] = isArrayIndex(nextSegment) ? [] : {};
      } else {
        current[index] = deepClone(current[index]);
      }
      current = current[index];
    } else {
      if (current[segment] === undefined || current[segment] === null) {
        current[segment] = isArrayIndex(nextSegment) ? [] : {};
      } else {
        current[segment] = deepClone(current[segment]);
      }
      current = current[segment];
    }
  }

  // Add the final value
  const lastSegment = segments[segments.length - 1];
  if (Array.isArray(current)) {
    const index = parseInt(lastSegment, 10);
    if (lastSegment === "-") {
      // "-" means append to array
      current.push(value);
    } else {
      // Insert at index
      current.splice(index, 0, value);
    }
  } else {
    current[lastSegment] = value;
  }

  return result;
}

/**
 * Apply a data model operation (A2UI v0.9 updateDataModel)
 * @param dataModel - Current data model
 * @param op - Operation type: "add", "replace", or "remove"
 * @param path - JSON Pointer path
 * @param value - Value for add/replace operations
 * @returns Updated data model
 */
export function applyDataModelOperation(
  dataModel: Record<string, any>,
  op: "add" | "replace" | "remove",
  path: string,
  value?: any
): Record<string, any> {
  switch (op) {
    case "add":
      return addByPointer(dataModel, path, value);
    case "replace":
      return setByPointer(dataModel, path, value);
    case "remove":
      return removeByPointer(dataModel, path);
    default:
      console.warn(`[JSON Pointer] Unknown operation: ${op}`);
      return dataModel;
  }
}

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Check if a string is a valid array index
 */
function isArrayIndex(segment: string): boolean {
  if (segment === "-") return true; // "-" is special append index
  const index = parseInt(segment, 10);
  return !isNaN(index) && index >= 0 && String(index) === segment;
}

/**
 * Deep clone an object or array
 */
function deepClone<T>(obj: T): T {
  if (obj === null || typeof obj !== "object") {
    return obj;
  }

  if (Array.isArray(obj)) {
    return obj.map((item) => deepClone(item)) as unknown as T;
  }

  const cloned: Record<string, any> = {};
  for (const key in obj) {
    if (Object.prototype.hasOwnProperty.call(obj, key)) {
      cloned[key] = deepClone((obj as Record<string, any>)[key]);
    }
  }
  return cloned as T;
}
