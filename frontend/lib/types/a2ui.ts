/**
 * A2UI (Agent-to-User Interface) Protocol Type Definitions
 * Based on A2UI Specification v0.9
 * https://github.com/google/A2UI/blob/main/specification/0.9/docs/a2ui_protocol.md
 */

// =============================================================================
// Common Types
// =============================================================================

/**
 * 値またはJSONポインターパス
 * v0.9: プレーン値とオブジェクト形式の両方をサポート
 */
export type StringOrPath = string | { path: string };

export type NumberOrPath = number | { path: string };

export type BooleanOrPath = boolean | { path: string };

// =============================================================================
// Theme
// =============================================================================

export interface A2UITheme {
  font?: string;
  primaryColor?: string; // hex color
}

// =============================================================================
// Actions
// =============================================================================

export interface A2UIAction {
  name: string;
  context?: Record<string, StringOrPath | NumberOrPath | BooleanOrPath>;
}

// =============================================================================
// Component Types (v0.9 flat structure with discriminator)
// =============================================================================

/**
 * Base interface for all components
 */
interface BaseComponent {
  id: string;
  component: string;
}

/**
 * Text Component
 */
export interface TextComponent extends BaseComponent {
  component: "Text";
  text: StringOrPath;
  styleHint?: "h1" | "h2" | "h3" | "h4" | "h5" | "body" | "caption" | "label";
}

/**
 * Image Component
 */
export interface ImageComponent extends BaseComponent {
  component: "Image";
  url: StringOrPath;
  fit?: "contain" | "cover" | "fill";
  usageHint?: "thumbnail" | "hero" | "icon";
  altText?: StringOrPath;
}

/**
 * Icon Component
 */
export interface IconComponent extends BaseComponent {
  component: "Icon";
  name?: string;  // Standard icon name
  path?: string;  // Custom icon path
}

/**
 * Button Component
 */
export interface ButtonComponent extends BaseComponent {
  component: "Button";
  child: string;  // Reference to child component ID
  primary?: boolean;
  disabled?: BooleanOrPath;
  action?: A2UIAction;
}

/**
 * TextField Component
 */
export interface TextFieldComponent extends BaseComponent {
  component: "TextField";
  label?: StringOrPath;
  text: StringOrPath;  // Bound to data path for two-way binding
  placeholder?: StringOrPath;
  textFieldType?: "shortText" | "longText" | "email" | "phone" | "number" | "password";
  // Note: "required" is NOT in A2UI v0.9 standard schema
  disabled?: BooleanOrPath;
}

/**
 * CheckBox Component
 */
export interface CheckBoxComponent extends BaseComponent {
  component: "CheckBox";
  label?: StringOrPath;
  checked: BooleanOrPath;
  disabled?: BooleanOrPath;
}

/**
 * ChoicePicker Component
 */
export interface ChoiceOption {
  id: string;
  label: StringOrPath;
  description?: StringOrPath;
}

export interface ChoicePickerComponent extends BaseComponent {
  component: "ChoicePicker";
  label?: StringOrPath;
  options: ChoiceOption[];
  selectedId: StringOrPath;
  multiSelect?: boolean;
  disabled?: BooleanOrPath;
}

/**
 * DateTimeInput Component
 */
export interface DateTimeInputComponent extends BaseComponent {
  component: "DateTimeInput";
  label?: StringOrPath;
  value: StringOrPath;  // ISO 8601 format
  mode?: "date" | "time" | "datetime";
  disabled?: BooleanOrPath;
}

/**
 * Slider Component
 */
export interface SliderComponent extends BaseComponent {
  component: "Slider";
  label?: StringOrPath;
  value: NumberOrPath;
  min?: number;
  max?: number;
  step?: number;
  disabled?: BooleanOrPath;
}

/**
 * Row Component (Horizontal layout)
 */
export interface RowComponent extends BaseComponent {
  component: "Row";
  children: string[];  // Array of component IDs
  alignment?: "start" | "center" | "end" | "stretch";
  distribution?: "start" | "center" | "end" | "spaceBetween" | "spaceAround";
  gap?: number;
}

/**
 * Column Component (Vertical layout)
 */
export interface ColumnComponent extends BaseComponent {
  component: "Column";
  children: string[];  // Array of component IDs
  alignment?: "start" | "center" | "end" | "stretch";
  distribution?: "start" | "center" | "end" | "spaceBetween" | "spaceAround";
  gap?: number;
}

/**
 * List Component
 */
export interface ListComponent extends BaseComponent {
  component: "List";
  children: string[];  // Template component IDs
  dataPath: string;  // JSON Pointer to array data
  direction?: "vertical" | "horizontal";
  gap?: number;
}

/**
 * Card Component
 */
export interface CardComponent extends BaseComponent {
  component: "Card";
  child: string;  // Reference to child component ID
  action?: A2UIAction;  // Click action
}

/**
 * Tabs Component
 */
export interface TabItem {
  id: string;
  label: StringOrPath;
  child: string;  // Component ID for tab content
}

export interface TabsComponent extends BaseComponent {
  component: "Tabs";
  tabs: TabItem[];
  selectedTabId: StringOrPath;
}

/**
 * Divider Component
 */
export interface DividerComponent extends BaseComponent {
  component: "Divider";
  orientation?: "horizontal" | "vertical";
}

/**
 * Modal Component
 */
export interface ModalComponent extends BaseComponent {
  component: "Modal";
  entryPointChild?: string;  // Trigger component ID
  contentChild: string;  // Modal content component ID
  open?: BooleanOrPath;
  title?: StringOrPath;
}

// =============================================================================
// Component Definition
// =============================================================================

export type A2UIComponent =
  | TextComponent
  | ImageComponent
  | IconComponent
  | ButtonComponent
  | TextFieldComponent
  | CheckBoxComponent
  | ChoicePickerComponent
  | DateTimeInputComponent
  | SliderComponent
  | RowComponent
  | ColumnComponent
  | ListComponent
  | CardComponent
  | TabsComponent
  | DividerComponent
  | ModalComponent;

// =============================================================================
// Surface & Messages
// =============================================================================

export interface A2UISurface {
  id: string;
  theme?: A2UITheme;
  components: A2UIComponent[];
  dataModel?: Record<string, any>;
}

/**
 * Server-to-Client Messages
 */
export interface CreateSurfaceMessage {
  type: "createSurface";
  surfaceId: string;
  theme?: A2UITheme;
}

export interface UpdateComponentsMessage {
  type: "updateComponents";
  surfaceId: string;
  components: A2UIComponent[];
}

export interface UpdateDataModelMessage {
  type: "updateDataModel";
  surfaceId: string;
  operations: DataModelOperation[];
}

export interface DeleteSurfaceMessage {
  type: "deleteSurface";
  surfaceId: string;
}

export type A2UIServerMessage =
  | CreateSurfaceMessage
  | UpdateComponentsMessage
  | UpdateDataModelMessage
  | DeleteSurfaceMessage;

/**
 * Data Model Operations (JSON Pointer based)
 */
export interface DataModelOperation {
  op: "add" | "replace" | "remove";
  path: string;  // JSON Pointer
  value?: any;
}

/**
 * Client-to-Server Messages (User Actions)
 */
export interface UserActionMessage {
  type: "userAction";
  name: string;
  surfaceId: string;
  sourceComponentId: string;
  timestamp: string;  // ISO 8601
  context?: Record<string, any>;
}

// =============================================================================
// AP2 Shopping Flow Specific A2UI Definitions
// =============================================================================

/**
 * Shipping Form A2UI Surface Definition
 */
export interface ShippingFormA2UI {
  surfaceId: string;
  surfaceType: "shipping_form";
  components: A2UIComponent[];
  dataModel: {
    shipping: {
      recipient: string;
      postal_code: string;
      city: string;
      region: string;
      address_line1: string;
      address_line2: string;
      country: string;
      phone_number: string;
    };
    formValid: boolean;
  };
}

/**
 * Credential Provider Selection A2UI Surface Definition
 */
export interface CPSelectionA2UI {
  surfaceId: string;
  surfaceType: "credential_provider_selection";
  components: A2UIComponent[];
  dataModel: {
    credentialProviders: Array<{
      id: string;
      name: string;
      description: string;
      supported_methods: string[];
    }>;
    selectedIndex: number | null;
  };
}

/**
 * Payment Method Selection A2UI Surface Definition
 */
export interface PaymentMethodSelectionA2UI {
  surfaceId: string;
  surfaceType: "payment_method_selection";
  components: A2UIComponent[];
  dataModel: {
    paymentMethods: Array<{
      id: string;
      type: string;
      brand: string;
      last4: string;
    }>;
    selectedIndex: number | null;
  };
}

/**
 * Product Carousel A2UI Surface Definition
 */
export interface ProductCarouselA2UI {
  surfaceId: string;
  surfaceType: "product_carousel";
  components: A2UIComponent[];
  dataModel: {
    products: Array<{
      id: string;
      sku: string;
      name: string;
      description: string;
      price: number;
      inventory_count: number;
      image_url: string;
    }>;
  };
}

/**
 * Cart Details Modal A2UI Surface Definition
 */
export interface CartDetailsA2UI {
  surfaceId: string;
  surfaceType: "cart_details";
  components: A2UIComponent[];
  dataModel: {
    cart: {
      id: string;
      name: string;
      description: string;
      merchant_name: string;
      items: Array<{
        label: string;
        description: string;
        image_url: string;
        unit_price: number;
        quantity: number;
        total_price: number;
      }>;
      subtotal: number;
      tax: number;
      shipping: number;
      total: number;
      shipping_address?: {
        recipient: string;
        postal_code: string;
        city: string;
        region: string;
        address_line: string[];
        phone_number: string;
      };
    };
    modalOpen: boolean;
  };
}

/**
 * A2UI v0.9 Protocol SSE Event Types
 *
 * These types represent A2UI protocol messages as SSE events.
 * Reference: https://a2ui.org/specification/v0.9-a2ui/
 */

/**
 * createSurface SSE Event - Initialize a new UI surface
 */
export interface A2UICreateSurfaceEvent {
  type: "a2ui_create_surface";
  surface_id: string;
  catalog_id?: string;
}

/**
 * updateComponents SSE Event - Provide component definitions
 */
export interface A2UIUpdateComponentsEvent {
  type: "a2ui_update_components";
  surface_id: string;
  components: A2UIComponent[];
}

/**
 * updateDataModel SSE Event - Send/modify data for components
 */
export interface A2UIUpdateDataModelEvent {
  type: "a2ui_update_data_model";
  surface_id: string;
  path: string;  // JSON Pointer
  op: "add" | "replace" | "remove";
  value?: Record<string, any>;
}

/**
 * deleteSurface SSE Event - Remove a surface
 */
export interface A2UIDeleteSurfaceEvent {
  type: "a2ui_delete_surface";
  surface_id: string;
}

/**
 * Union type for all A2UI v0.9 SSE events
 */
export type A2UISSEEvent =
  | A2UICreateSurfaceEvent
  | A2UIUpdateComponentsEvent
  | A2UIUpdateDataModelEvent
  | A2UIDeleteSurfaceEvent;

/**
 * @deprecated Legacy A2UI SSE event types (pre-v0.9)
 * These are kept for backward compatibility during migration
 */
export interface A2UIShippingFormEvent {
  type: "a2ui_surface";
  surface: ShippingFormA2UI;
}

export interface A2UICPSelectionEvent {
  type: "a2ui_surface";
  surface: CPSelectionA2UI;
}

export interface A2UIPaymentMethodSelectionEvent {
  type: "a2ui_surface";
  surface: PaymentMethodSelectionA2UI;
}

export interface A2UIProductCarouselEvent {
  type: "a2ui_surface";
  surface: ProductCarouselA2UI;
}

export interface A2UICartDetailsEvent {
  type: "a2ui_surface";
  surface: CartDetailsA2UI;
}

/** @deprecated Use A2UISSEEvent instead */
export type LegacyA2UISSEEvent =
  | A2UIShippingFormEvent
  | A2UICPSelectionEvent
  | A2UIPaymentMethodSelectionEvent
  | A2UIProductCarouselEvent
  | A2UICartDetailsEvent;
