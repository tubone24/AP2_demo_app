import {
  parseJsonPointer,
  getByPointer,
  setByPointer,
  removeByPointer,
  addByPointer,
  applyDataModelOperation,
} from "../jsonPointer";

describe("JSON Pointer (RFC 6901)", () => {
  describe("parseJsonPointer", () => {
    it("parses root path", () => {
      expect(parseJsonPointer("/")).toEqual([]);
      expect(parseJsonPointer("")).toEqual([]);
    });

    it("parses simple paths", () => {
      expect(parseJsonPointer("/foo")).toEqual(["foo"]);
      expect(parseJsonPointer("/foo/bar")).toEqual(["foo", "bar"]);
    });

    it("parses array indices", () => {
      expect(parseJsonPointer("/items/0")).toEqual(["items", "0"]);
      expect(parseJsonPointer("/items/0/name")).toEqual(["items", "0", "name"]);
    });

    it("handles escaped characters", () => {
      // ~0 = ~, ~1 = /
      expect(parseJsonPointer("/a~0b")).toEqual(["a~b"]);
      expect(parseJsonPointer("/a~1b")).toEqual(["a/b"]);
      expect(parseJsonPointer("/~0~1")).toEqual(["~/"]);
    });

    it("throws on invalid pointer", () => {
      expect(() => parseJsonPointer("foo")).toThrow();
      expect(() => parseJsonPointer("foo/bar")).toThrow();
    });
  });

  describe("getByPointer", () => {
    const testObj = {
      shipping: {
        city: "Tokyo",
        postal_code: "100-0001",
      },
      items: [
        { name: "Product A", quantity: 2 },
        { name: "Product B", quantity: 1 },
      ],
      total: 5000,
    };

    it("gets root", () => {
      expect(getByPointer(testObj, "/")).toEqual(testObj);
    });

    it("gets nested object value", () => {
      expect(getByPointer(testObj, "/shipping/city")).toBe("Tokyo");
      expect(getByPointer(testObj, "/shipping/postal_code")).toBe("100-0001");
    });

    it("gets array element", () => {
      expect(getByPointer(testObj, "/items/0")).toEqual({ name: "Product A", quantity: 2 });
      expect(getByPointer(testObj, "/items/1/name")).toBe("Product B");
    });

    it("gets primitive value", () => {
      expect(getByPointer(testObj, "/total")).toBe(5000);
    });

    it("returns undefined for non-existent path", () => {
      expect(getByPointer(testObj, "/nonexistent")).toBeUndefined();
      expect(getByPointer(testObj, "/shipping/country")).toBeUndefined();
      expect(getByPointer(testObj, "/items/10")).toBeUndefined();
    });
  });

  describe("setByPointer", () => {
    it("replaces root", () => {
      const obj = { foo: "bar" };
      const result = setByPointer(obj, "/", { new: "value" });
      expect(result).toEqual({ new: "value" });
      expect(obj).toEqual({ foo: "bar" }); // Original unchanged
    });

    it("sets nested value", () => {
      const obj = { shipping: { city: "Tokyo" } };
      const result = setByPointer(obj, "/shipping/city", "Osaka");
      expect(result.shipping.city).toBe("Osaka");
      expect(obj.shipping.city).toBe("Tokyo"); // Original unchanged
    });

    it("sets array element", () => {
      const obj = { items: [1, 2, 3] };
      const result = setByPointer(obj, "/items/1", 99);
      expect(result.items).toEqual([1, 99, 3]);
      expect(obj.items).toEqual([1, 2, 3]); // Original unchanged
    });

    it("creates intermediate objects", () => {
      const obj = {};
      const result = setByPointer(obj, "/a/b/c", "value");
      expect(result).toEqual({ a: { b: { c: "value" } } });
    });

    it("creates intermediate arrays", () => {
      const obj = {};
      const result = setByPointer(obj, "/items/0/name", "Product");
      expect(result).toEqual({ items: [{ name: "Product" }] });
    });
  });

  describe("removeByPointer", () => {
    it("removes object property", () => {
      const obj = { a: 1, b: 2, c: 3 };
      const result = removeByPointer(obj, "/b");
      expect(result).toEqual({ a: 1, c: 3 });
      expect(obj).toEqual({ a: 1, b: 2, c: 3 }); // Original unchanged
    });

    it("removes nested property", () => {
      const obj = { shipping: { city: "Tokyo", postal: "100" } };
      const result = removeByPointer(obj, "/shipping/postal");
      expect(result.shipping).toEqual({ city: "Tokyo" });
    });

    it("removes array element", () => {
      const obj = { items: [1, 2, 3] };
      const result = removeByPointer(obj, "/items/1");
      expect(result.items).toEqual([1, 3]);
    });

    it("returns unchanged for non-existent path", () => {
      const obj = { a: 1 };
      const result = removeByPointer(obj, "/nonexistent");
      expect(result).toEqual({ a: 1 });
    });

    it("removes root returns empty object", () => {
      const obj = { a: 1, b: 2 };
      const result = removeByPointer(obj, "/");
      expect(result).toEqual({});
    });
  });

  describe("addByPointer", () => {
    it("adds object property", () => {
      const obj = { a: 1 };
      const result = addByPointer(obj, "/b", 2);
      expect(result).toEqual({ a: 1, b: 2 });
    });

    it("inserts array element", () => {
      const obj = { items: [1, 3] };
      const result = addByPointer(obj, "/items/1", 2);
      expect(result.items).toEqual([1, 2, 3]);
    });

    it("appends to array with -", () => {
      const obj = { items: [1, 2] };
      const result = addByPointer(obj, "/items/-", 3);
      expect(result.items).toEqual([1, 2, 3]);
    });

    it("creates intermediate structures", () => {
      const obj = {};
      const result = addByPointer(obj, "/shipping/address/city", "Tokyo");
      expect(result).toEqual({
        shipping: { address: { city: "Tokyo" } },
      });
    });
  });

  describe("applyDataModelOperation", () => {
    const initialData = {
      shipping: {
        city: "Tokyo",
        postal_code: "100-0001",
      },
      items: [
        { name: "Product A", quantity: 2 },
      ],
    };

    it("handles replace at root", () => {
      const newData = { completely: "new" };
      const result = applyDataModelOperation(initialData, "replace", "/", newData);
      expect(result).toEqual(newData);
    });

    it("handles replace at path", () => {
      const result = applyDataModelOperation(initialData, "replace", "/shipping/city", "Osaka");
      expect(result.shipping.city).toBe("Osaka");
      expect(result.shipping.postal_code).toBe("100-0001"); // Unchanged
    });

    it("handles add operation", () => {
      const result = applyDataModelOperation(initialData, "add", "/shipping/country", "Japan");
      expect(result.shipping.country).toBe("Japan");
    });

    it("handles remove operation", () => {
      const result = applyDataModelOperation(initialData, "remove", "/shipping/postal_code");
      expect(result.shipping.postal_code).toBeUndefined();
      expect(result.shipping.city).toBe("Tokyo"); // Unchanged
    });

    it("handles array operations", () => {
      const addResult = applyDataModelOperation(
        initialData,
        "add",
        "/items/-",
        { name: "Product B", quantity: 1 }
      );
      expect(addResult.items).toHaveLength(2);
      expect(addResult.items[1].name).toBe("Product B");
    });

    it("handles unknown operation gracefully", () => {
      const consoleSpy = jest.spyOn(console, "warn").mockImplementation();
      const result = applyDataModelOperation(
        initialData,
        "unknown" as any,
        "/shipping/city",
        "Test"
      );
      expect(result).toEqual(initialData);
      expect(consoleSpy).toHaveBeenCalled();
      consoleSpy.mockRestore();
    });
  });
});
