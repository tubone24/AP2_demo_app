/**
 * A2UI Surface Adapters
 *
 * These adapters convert A2UI surface definitions to the current component props format,
 * allowing a gradual migration to A2UI without changing existing component behavior.
 */

import type {
  ShippingFormA2UI,
  CPSelectionA2UI,
  PaymentMethodSelectionA2UI,
  ProductCarouselA2UI,
  CartDetailsA2UI,
  A2UIComponent,
  StringOrPath,
  NumberOrPath,
  BooleanOrPath,
} from "@/lib/types/a2ui";
import type { FormField, CredentialProvider, PaymentMethodOption, Product } from "@/lib/types/chat";

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Resolve a StringOrPath to a string value
 */
function resolveString(value: StringOrPath | undefined, dataModel: Record<string, any>): string {
  if (!value) return "";
  if (value.literalString !== undefined) return value.literalString;
  if (value.path) {
    return getValueByPath(dataModel, value.path) ?? "";
  }
  return "";
}

/**
 * Resolve a NumberOrPath to a number value
 */
function resolveNumber(value: NumberOrPath | undefined, dataModel: Record<string, any>): number {
  if (!value) return 0;
  if (value.literalNumber !== undefined) return value.literalNumber;
  if (value.path) {
    return getValueByPath(dataModel, value.path) ?? 0;
  }
  return 0;
}

/**
 * Resolve a BooleanOrPath to a boolean value
 */
function resolveBoolean(value: BooleanOrPath | undefined, dataModel: Record<string, any>): boolean {
  if (!value) return false;
  if (value.literalBoolean !== undefined) return value.literalBoolean;
  if (value.path) {
    return getValueByPath(dataModel, value.path) ?? false;
  }
  return false;
}

/**
 * Get value from data model by JSON Pointer path
 */
function getValueByPath(dataModel: Record<string, any>, path: string): any {
  if (!path.startsWith("/")) return undefined;

  const parts = path.slice(1).split("/");
  let current: any = dataModel;

  for (const part of parts) {
    if (current === undefined || current === null) return undefined;
    current = current[part];
  }

  return current;
}

// =============================================================================
// Shipping Form Adapter
// =============================================================================

export interface ShippingFormAdapterResult {
  fields: FormField[];
  initialData: Record<string, string>;
}

/**
 * Convert A2UI ShippingFormA2UI to ShippingAddressForm props
 */
export function adaptShippingFormA2UI(surface: ShippingFormA2UI): ShippingFormAdapterResult {
  const fields: FormField[] = [];
  const initialData: Record<string, string> = {};

  // Find TextField and ChoicePicker components
  for (const comp of surface.components) {
    if ("TextField" in comp.component) {
      const textField = comp.component.TextField;
      const label = resolveString(textField.label, surface.dataModel);
      const path = textField.text.path;

      if (path) {
        // Extract field name from path (e.g., "/shipping/recipient" -> "recipient")
        const fieldName = path.split("/").pop() || "";

        // A2UI v0.9: required indicator is shown in label text (e.g., "Name *")
        // TextField.required is NOT in v0.9 standard schema
        const isRequired = label.endsWith(" *");
        const cleanLabel = label.replace(/ \*$/, "");

        let fieldType: FormField["type"] = "text";
        if (textField.textFieldType === "email") fieldType = "text";
        else if (textField.textFieldType === "phone") fieldType = "text";
        else if (textField.textFieldType === "number") fieldType = "number";
        else if (textField.textFieldType === "longText") fieldType = "textarea";

        fields.push({
          name: fieldName,
          label: cleanLabel,
          type: fieldType,
          required: isRequired,
          placeholder: resolveString(textField.placeholder, surface.dataModel) || undefined,
        });

        // Get initial value from data model
        const initialValue = getValueByPath(surface.dataModel, path);
        if (initialValue !== undefined) {
          initialData[fieldName] = String(initialValue);
        }
      }
    } else if ("ChoicePicker" in comp.component) {
      const picker = comp.component.ChoicePicker;
      const label = resolveString(picker.label, surface.dataModel);
      const path = picker.selectedId.path;

      if (path) {
        const fieldName = path.split("/").pop() || "";
        const isRequired = label.endsWith(" *");
        const cleanLabel = label.replace(/ \*$/, "");

        fields.push({
          name: fieldName,
          label: cleanLabel,
          type: "select",
          required: isRequired,
          options: picker.options.map((opt) => ({
            value: opt.id,
            label: resolveString(opt.label, surface.dataModel),
          })),
        });

        const initialValue = getValueByPath(surface.dataModel, path);
        if (initialValue !== undefined) {
          initialData[fieldName] = String(initialValue);
        }
      }
    }
  }

  return { fields, initialData };
}

// =============================================================================
// Credential Provider Selection Adapter
// =============================================================================

export interface CPSelectionAdapterResult {
  providers: CredentialProvider[];
  onSelect: (index: number, providerId: string) => void;
}

/**
 * Convert A2UI CPSelectionA2UI to credential provider list props
 */
export function adaptCPSelectionA2UI(surface: CPSelectionA2UI): Omit<CPSelectionAdapterResult, "onSelect"> {
  const providers: CredentialProvider[] = surface.dataModel.credentialProviders.map((cp) => ({
    id: cp.id,
    name: cp.name,
    url: "", // Not provided in A2UI data model
    description: cp.description,
    supported_methods: cp.supported_methods,
  }));

  return { providers };
}

// =============================================================================
// Payment Method Selection Adapter
// =============================================================================

export interface PaymentMethodSelectionAdapterResult {
  paymentMethods: PaymentMethodOption[];
  onSelect: (index: number, paymentMethodId: string) => void;
}

/**
 * Convert A2UI PaymentMethodSelectionA2UI to payment method list props
 */
export function adaptPaymentMethodSelectionA2UI(
  surface: PaymentMethodSelectionA2UI
): Omit<PaymentMethodSelectionAdapterResult, "onSelect"> {
  const paymentMethods: PaymentMethodOption[] = surface.dataModel.paymentMethods.map((pm) => ({
    id: pm.id,
    type: pm.type,
    brand: pm.brand,
    last4: pm.last4,
  }));

  return { paymentMethods };
}

// =============================================================================
// Product Carousel Adapter
// =============================================================================

export interface ProductCarouselAdapterResult {
  products: Product[];
}

/**
 * Convert A2UI ProductCarouselA2UI to ProductCarousel props
 */
export function adaptProductCarouselA2UI(surface: ProductCarouselA2UI): ProductCarouselAdapterResult {
  const products: Product[] = surface.dataModel.products.map((p) => ({
    id: p.id,
    sku: p.sku,
    name: p.name,
    description: p.description,
    price: p.price,
    inventory_count: p.inventory_count,
    image_url: p.image_url,
    metadata: p.image_url ? { image_url: p.image_url } : undefined,
  }));

  return { products };
}

// =============================================================================
// Cart Details Modal Adapter
// =============================================================================

export interface CartDetailsAdapterResult {
  cartCandidate: {
    artifact_id: string;
    artifact_name: string;
    cart_mandate: {
      contents: {
        id: string;
        user_cart_confirmation_required: boolean;
        payment_request: {
          method_data: any[];
          details: {
            id: string;
            display_items: Array<{
              label: string;
              amount: { currency: string; value: number };
              pending?: boolean;
              refund_period?: number;
            }>;
            total: {
              label: string;
              amount: { currency: string; value: number };
            };
            shipping_options?: Array<{
              id: string;
              label: string;
              amount: { currency: string; value: number };
              selected?: boolean;
            }>;
          };
          shipping_address?: {
            recipient?: string;
            postal_code?: string;
            city?: string;
            region?: string;
            country?: string;
            address_line?: string[];
            phone_number?: string;
          };
        };
        cart_expiry: string;
        merchant_name: string;
      };
      _metadata?: {
        cart_name?: string;
        cart_description?: string;
        raw_items?: any[];
      };
    };
  };
  open: boolean;
}

/**
 * Convert A2UI CartDetailsA2UI to CartDetailsModal props
 */
export function adaptCartDetailsA2UI(surface: CartDetailsA2UI): CartDetailsAdapterResult {
  const cart = surface.dataModel.cart;

  // Reconstruct display_items from cart items
  const displayItems = cart.items.map((item) => ({
    label: item.label,
    amount: { currency: "JPY", value: item.total_price },
    pending: false,
    refund_period: 14, // Default refund period for products
  }));

  // Add tax item if present
  if (cart.tax > 0) {
    displayItems.push({
      label: "消費税",
      amount: { currency: "JPY", value: cart.tax },
      pending: false,
      refund_period: 0,
    });
  }

  // Add shipping item if present
  if (cart.shipping > 0) {
    displayItems.push({
      label: "送料",
      amount: { currency: "JPY", value: cart.shipping },
      pending: false,
      refund_period: 0,
    });
  }

  const cartCandidate: CartDetailsAdapterResult["cartCandidate"] = {
    artifact_id: cart.id,
    artifact_name: cart.name,
    cart_mandate: {
      contents: {
        id: cart.id,
        user_cart_confirmation_required: true,
        payment_request: {
          method_data: [],
          details: {
            id: cart.id,
            display_items: displayItems,
            total: {
              label: "合計",
              amount: { currency: "JPY", value: cart.total },
            },
          },
          shipping_address: cart.shipping_address
            ? {
                recipient: cart.shipping_address.recipient,
                postal_code: cart.shipping_address.postal_code,
                city: cart.shipping_address.city,
                region: cart.shipping_address.region,
                address_line: cart.shipping_address.address_line,
                phone_number: cart.shipping_address.phone_number,
              }
            : undefined,
        },
        cart_expiry: "",
        merchant_name: cart.merchant_name,
      },
      _metadata: {
        cart_name: cart.name,
        cart_description: cart.description,
        raw_items: cart.items.map((item) => ({
          description: item.description,
          image_url: item.image_url,
          unit_price: { currency: "JPY", value: item.unit_price },
          quantity: item.quantity,
        })),
      },
    },
  };

  return {
    cartCandidate,
    open: surface.dataModel.modalOpen,
  };
}

// =============================================================================
// Generic A2UI Surface Adapter
// =============================================================================

export type A2UISurfaceType =
  | ShippingFormA2UI
  | CPSelectionA2UI
  | PaymentMethodSelectionA2UI
  | ProductCarouselA2UI
  | CartDetailsA2UI;

export type AdaptedResult =
  | { type: "shipping_form"; data: ShippingFormAdapterResult }
  | { type: "credential_provider_selection"; data: Omit<CPSelectionAdapterResult, "onSelect"> }
  | { type: "payment_method_selection"; data: Omit<PaymentMethodSelectionAdapterResult, "onSelect"> }
  | { type: "product_carousel"; data: ProductCarouselAdapterResult }
  | { type: "cart_details"; data: CartDetailsAdapterResult };

/**
 * Adapt any A2UI surface to its corresponding component props
 */
export function adaptA2UISurface(surface: A2UISurfaceType): AdaptedResult | null {
  switch (surface.surfaceType) {
    case "shipping_form":
      return {
        type: "shipping_form",
        data: adaptShippingFormA2UI(surface as ShippingFormA2UI),
      };
    case "credential_provider_selection":
      return {
        type: "credential_provider_selection",
        data: adaptCPSelectionA2UI(surface as CPSelectionA2UI),
      };
    case "payment_method_selection":
      return {
        type: "payment_method_selection",
        data: adaptPaymentMethodSelectionA2UI(surface as PaymentMethodSelectionA2UI),
      };
    case "product_carousel":
      return {
        type: "product_carousel",
        data: adaptProductCarouselA2UI(surface as ProductCarouselA2UI),
      };
    case "cart_details":
      return {
        type: "cart_details",
        data: adaptCartDetailsA2UI(surface as CartDetailsA2UI),
      };
    default:
      return null;
  }
}
