/**
 * Chat UI型定義
 * demo_app_v2.mdのSSE仕様に準拠
 */

// SSEイベント型
export type SSEEventType =
  | "agent_text"
  | "agent_thinking"  // LLMの思考過程（JSON出力など）
  | "agent_thinking_complete"  // LLM思考完了通知
  | "agent_text_chunk"  // エージェント応答のストリーミングチャンク
  | "agent_text_complete"  // エージェント応答完了通知
  | "signature_request"
  | "cart_options"
  | "product_list"
  | "credential_provider_selection"
  | "shipping_form_request"
  | "payment_method_selection"
  | "webauthn_request"
  | "stepup_authentication_request"  // AP2完全準拠: 3D Secure 2.0認証リクエスト
  | "step_up_redirect"
  | "payment_completed"  // AP2完全準拠: 決済完了通知
  | "a2ui_surface"  // A2UI Surface (Agent-to-User Interface) - レガシー
  // A2UI v0.9 Protocol Events
  | "a2ui_create_surface"
  | "a2ui_update_components"
  | "a2ui_update_data_model"
  | "a2ui_delete_surface"
  | "done"
  | "error";

// 基本SSEイベント
export interface SSEEvent {
  type: SSEEventType;
}

// エージェントテキストイベント
export interface AgentTextEvent extends SSEEvent {
  type: "agent_text";
  content: string;
}

// LLM思考過程イベント
export interface AgentThinkingEvent extends SSEEvent {
  type: "agent_thinking";
  content?: string;
}

// LLM思考完了イベント
export interface AgentThinkingCompleteEvent extends SSEEvent {
  type: "agent_thinking_complete";
  content?: string;
}

// エージェント応答チャンクイベント
export interface AgentTextChunkEvent extends SSEEvent {
  type: "agent_text_chunk";
  content?: string;
}

// エージェント応答完了イベント
export interface AgentTextCompleteEvent extends SSEEvent {
  type: "agent_text_complete";
  content?: string;
}

// 署名リクエストイベント
export interface SignatureRequestEvent extends SSEEvent {
  type: "signature_request";
  mandate: IntentMandate | CartMandate | PaymentMandate;
  mandate_type: "intent" | "cart" | "payment";
}

// カートオプションイベント（カルーセル用）
export interface CartOptionsEvent extends SSEEvent {
  type: "cart_options";
  items: Product[];
}

// 商品リストイベント
export interface ProductListEvent extends SSEEvent {
  type: "product_list";
  products: Product[];
}

// Credential Provider選択イベント
export interface CredentialProviderSelectionEvent extends SSEEvent {
  type: "credential_provider_selection";
  providers: CredentialProvider[];
}

// 配送先フォームリクエストイベント
export interface ShippingFormRequestEvent extends SSEEvent {
  type: "shipping_form_request";
  form_schema: FormSchema;
}

// 支払い方法選択イベント
export interface PaymentMethodSelectionEvent extends SSEEvent {
  type: "payment_method_selection";
  payment_methods: PaymentMethodOption[];
}

// WebAuthn認証リクエストイベント
export interface WebAuthnRequestEvent extends SSEEvent {
  type: "webauthn_request";
  challenge: string;
  rp_id: string;
  timeout: number;
}

// Stepup認証リクエストイベント（AP2完全準拠: 3D Secure 2.0）
export interface StepupAuthenticationRequestEvent extends SSEEvent {
  type: "stepup_authentication_request";
  stepup_method: string;
  payment_method_id: string;
  brand: string;
  last4: string;
  challenge_url: string;
}

// Step-upリダイレクトイベント（AP2 Step 13対応）
export interface StepUpRedirectEvent extends SSEEvent {
  type: "step_up_redirect";
  step_up_url: string;
  session_id: string;
  reason: string;
}

// 完了イベント
export interface DoneEvent extends SSEEvent {
  type: "done";
}

// エラーイベント
export interface ErrorEvent extends SSEEvent {
  type: "error";
  message: string;
}

// 決済完了イベント（AP2完全準拠）
export interface PaymentCompletedEvent extends SSEEvent {
  type: "payment_completed";
  transaction_id: string;
  product_name: string;
  amount: number;
  currency: string;
  merchant_name: string;
  receipt_url: string;
  status: string;
}

// A2UI Surface イベント（Agent-to-User Interface）- レガシー形式
/** @deprecated Use A2UI v0.9 events instead */
export interface A2UISurfaceEvent extends SSEEvent {
  type: "a2ui_surface";
  surface: {
    surfaceId: string;
    surfaceType: string;
    components: any[];
    dataModel: Record<string, any>;
  };
}

// A2UI v0.9 Protocol Events
// Reference: https://a2ui.org/specification/v0.9-a2ui/

export interface A2UICreateSurfaceEvent extends SSEEvent {
  type: "a2ui_create_surface";
  surface_id: string;
  catalog_id?: string;
}

export interface A2UIUpdateComponentsEvent extends SSEEvent {
  type: "a2ui_update_components";
  surface_id: string;
  components: any[];
}

export interface A2UIUpdateDataModelEvent extends SSEEvent {
  type: "a2ui_update_data_model";
  surface_id: string;
  path: string;
  op: "add" | "replace" | "remove";
  value?: Record<string, any>;
}

export interface A2UIDeleteSurfaceEvent extends SSEEvent {
  type: "a2ui_delete_surface";
  surface_id: string;
}

// すべてのSSEイベント型
export type ChatSSEEvent =
  | AgentTextEvent
  | AgentThinkingEvent
  | AgentThinkingCompleteEvent
  | AgentTextChunkEvent
  | AgentTextCompleteEvent
  | SignatureRequestEvent
  | CartOptionsEvent
  | ProductListEvent
  | CredentialProviderSelectionEvent
  | ShippingFormRequestEvent
  | PaymentMethodSelectionEvent
  | WebAuthnRequestEvent
  | StepupAuthenticationRequestEvent
  | StepUpRedirectEvent
  | PaymentCompletedEvent
  | A2UISurfaceEvent
  // A2UI v0.9 Protocol Events
  | A2UICreateSurfaceEvent
  | A2UIUpdateComponentsEvent
  | A2UIUpdateDataModelEvent
  | A2UIDeleteSurfaceEvent
  | DoneEvent
  | ErrorEvent;

// チャットメッセージ
export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  content: string;
  timestamp: Date;
  metadata?: {
    products?: Product[];
    mandate?: any;
    mandate_type?: string;
    payment_result?: {
      status: "success" | "failed";
      transaction_id: string;
      receipt_url: string;
      product_name?: string;
      amount?: number;
    };
  };
}

// 商品
export interface Product {
  id: string;
  sku: string;
  name: string;
  description: string;
  price: number; // cents
  inventory_count: number;
  image_url?: string;
  metadata?: {
    image_url?: string;
    [key: string]: any;
  };
}

// Amount（AP2仕様）
export interface Amount {
  value: string;
  currency: string;
}

// IntentMandate
export interface IntentMandate {
  id: string;
  user_id: string;
  max_amount: Amount;
  allowed_merchants?: string[];
  allowed_categories?: string[];
  expires_at?: string;
  user_signature?: Signature;
}

// CartMandate
export interface CartMandate {
  id: string;
  merchant_id: string;
  items: CartItem[];
  total_amount: Amount;
  merchant_signature?: Signature;
  user_signature?: Signature;
  intent_mandate_id?: string;
}

// CartItem
export interface CartItem {
  product_id: string;
  sku: string;
  name: string;
  quantity: number;
  unit_price: Amount;
  total_price: Amount;
}

// PaymentMandate
export interface PaymentMandate {
  id: string;
  cart_mandate_id: string;
  intent_mandate_id: string;
  payment_method: PaymentMethod;
  amount: Amount;
  payer_id: string;
  payee_id: string;
  risk_score?: number;
  fraud_indicators?: string[];
}

// PaymentMethod
export interface PaymentMethod {
  type: "card" | "wallet" | "bank_transfer";
  token?: string;
  last4?: string;
  brand?: string;
}

// Signature（AP2仕様）
export interface Signature {
  algorithm: string;
  public_key: string;
  value: string;
}

// WebAuthn Attestation
export interface WebAuthnAttestation {
  id: string;
  rawId: string;
  response: {
    clientDataJSON: string;
    authenticatorData: string;
    signature: string;
    userHandle?: string;
  };
  type: "public-key";
  attestation_type?: string;
  challenge?: string;
  // 登録専用フィールド（registerPasskey()の戻り値に含まれる）
  attestationObject?: string;  // attestationObject（Base64URL）
  transports?: string[];  // 利用可能なトランスポート
}

// Credential Provider
export interface CredentialProvider {
  id: string;
  name: string;
  url: string;
  description: string;
  logo_url?: string;
  supported_methods: string[];
}

// Form Schema（配送先フォーム）
export interface FormSchema {
  type: string;
  fields: FormField[];
}

export interface FormField {
  name: string;
  label: string;
  type: "text" | "select" | "textarea" | "number";
  required: boolean;
  placeholder?: string;
  pattern?: string;
  options?: Array<{ value: string; label: string }>;
  default?: string;
}

// Payment Method Option（支払い方法選択肢）
export interface PaymentMethodOption {
  id: string;
  type: string;
  brand?: string;
  last4?: string;
  expires_at?: string;
}
