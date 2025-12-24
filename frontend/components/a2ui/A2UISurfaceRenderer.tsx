/**
 * A2UI v0.9 Surface Renderer
 *
 * Renders A2UI components from surface state.
 * Handles two-way data binding and action dispatch.
 *
 * @see https://github.com/google/A2UI/blob/main/specification/0.9/
 */

"use client";

import React, { useCallback, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  A2UIComponent,
  StringOrPath,
  BooleanOrPath,
  NumberOrPath,
  A2UIAction,
} from "@/lib/types/a2ui";

// =============================================================================
// Types
// =============================================================================

export interface A2UISurfaceRendererProps {
  surfaceId: string;
  components: A2UIComponent[];
  dataModel: Record<string, any>;
  onDataModelChange: (path: string, value: any) => void;
  onAction: (action: A2UIAction, surfaceId: string, sourceComponentId: string) => void;
}

// =============================================================================
// Path Resolution Utilities
// =============================================================================

/**
 * Resolve a JSON Pointer path against the data model
 */
function resolvePath(path: string, dataModel: Record<string, any>): any {
  if (!path || path === "/") return dataModel;

  const parts = path.replace(/^\//, "").split("/");
  let current: any = dataModel;

  for (const part of parts) {
    if (current === null || current === undefined) return undefined;
    if (typeof current === "object" && part in current) {
      current = current[part];
    } else if (Array.isArray(current)) {
      const index = parseInt(part, 10);
      if (!isNaN(index)) {
        current = current[index];
      } else {
        return undefined;
      }
    } else {
      return undefined;
    }
  }

  return current;
}

/**
 * Resolve StringOrPath to actual string value
 * v0.9: プレーン文字列とオブジェクト形式の両方をサポート
 */
function resolveString(value: StringOrPath | undefined, dataModel: Record<string, any>): string {
  if (!value) return "";
  // v0.9: プレーン文字列の場合はそのまま返す
  if (typeof value === "string") return value;
  // オブジェクト形式の場合、pathで解決
  if (typeof value === "object" && value.path) {
    return String(resolvePath(value.path, dataModel) ?? "");
  }
  return "";
}

/**
 * Resolve BooleanOrPath to actual boolean value
 * v0.9: プレーンbooleanとオブジェクト形式の両方をサポート
 */
function resolveBoolean(value: BooleanOrPath | undefined, dataModel: Record<string, any>): boolean {
  if (value === undefined) return false;
  // v0.9: プレーンbooleanの場合はそのまま返す
  if (typeof value === "boolean") return value;
  // オブジェクト形式の場合、pathで解決
  if (typeof value === "object" && value.path) {
    return Boolean(resolvePath(value.path, dataModel));
  }
  return false;
}

/**
 * Resolve NumberOrPath to actual number value
 * v0.9: プレーン数値とオブジェクト形式の両方をサポート
 */
function resolveNumber(value: NumberOrPath | undefined, dataModel: Record<string, any>): number {
  if (value === undefined) return 0;
  // v0.9: プレーン数値の場合はそのまま返す
  if (typeof value === "number") return value;
  // オブジェクト形式の場合、pathで解決
  if (typeof value === "object" && value.path) {
    return Number(resolvePath(value.path, dataModel) ?? 0);
  }
  return 0;
}

// =============================================================================
// Component Renderer
// =============================================================================

interface ComponentRendererProps {
  component: A2UIComponent;
  componentsMap: Map<string, A2UIComponent>;
  dataModel: Record<string, any>;
  onDataModelChange: (path: string, value: any) => void;
  onAction: (action: A2UIAction, sourceComponentId: string) => void;
}

function ComponentRenderer({
  component,
  componentsMap,
  dataModel,
  onDataModelChange,
  onAction,
}: ComponentRendererProps): React.ReactElement | null {
  // Helper to render child components by ID
  const renderChild = (childId: string) => {
    const child = componentsMap.get(childId);
    if (!child) return null;
    return (
      <ComponentRenderer
        key={childId}
        component={child}
        componentsMap={componentsMap}
        dataModel={dataModel}
        onDataModelChange={onDataModelChange}
        onAction={onAction}
      />
    );
  };

  // Text Component
  if (component.component === "Text") {
    const { text, styleHint } = component;
    const textValue = resolveString(text, dataModel);

    const styleMap: Record<string, string> = {
      h1: "text-2xl font-bold",
      h2: "text-xl font-semibold",
      h3: "text-lg font-semibold",
      h4: "text-base font-medium",
      h5: "text-sm font-medium",
      body: "text-base",
      caption: "text-sm text-muted-foreground",
      label: "text-sm font-medium",
    };

    const className = styleMap[styleHint || "body"] || "text-base";

    return <p className={className}>{textValue}</p>;
  }

  // TextField Component
  if (component.component === "TextField") {
    const { id, label, text, placeholder, textFieldType, disabled } = component;
    const labelValue = resolveString(label, dataModel);
    const textValue = resolveString(text, dataModel);
    const placeholderValue = resolveString(placeholder, dataModel);
    const isDisabled = resolveBoolean(disabled, dataModel);

    // Extract path for two-way binding
    const dataPath = typeof text === "object" && text.path ? text.path : undefined;

    // Map A2UI textFieldType to HTML input type
    const inputTypeMap: Record<string, string> = {
      shortText: "text",
      longText: "text",
      email: "email",
      phone: "tel",
      number: "number",
      password: "password",
    };
    const inputType = inputTypeMap[textFieldType || "shortText"] || "text";

    return (
      <div className="space-y-2">
        {labelValue && <Label htmlFor={id}>{labelValue}</Label>}
        <Input
          id={id}
          type={inputType}
          value={textValue}
          placeholder={placeholderValue}
          disabled={isDisabled}
          onChange={(e) => {
            if (dataPath) {
              onDataModelChange(dataPath, e.target.value);
            }
          }}
        />
      </div>
    );
  }

  // Button Component
  if (component.component === "Button") {
    const { id, child, primary, disabled, action } = component;
    const isDisabled = resolveBoolean(disabled, dataModel);

    // Render button child (usually a Text component)
    const childContent = renderChild(child);

    return (
      <Button
        variant={primary ? "default" : "outline"}
        disabled={isDisabled}
        onClick={() => {
          if (action) {
            onAction(action, id);
          }
        }}
      >
        {childContent}
      </Button>
    );
  }

  // CheckBox Component (using Switch as fallback)
  if (component.component === "CheckBox") {
    const { id, label, checked, disabled } = component;
    const labelValue = resolveString(label, dataModel);
    const isChecked = resolveBoolean(checked, dataModel);
    const isDisabled = resolveBoolean(disabled, dataModel);
    const dataPath = typeof checked === "object" && checked.path ? checked.path : undefined;

    return (
      <div className="flex items-center space-x-2">
        <Switch
          id={id}
          checked={isChecked}
          disabled={isDisabled}
          onCheckedChange={(value: boolean) => {
            if (dataPath) {
              onDataModelChange(dataPath, value);
            }
          }}
        />
        {labelValue && <Label htmlFor={id}>{labelValue}</Label>}
      </div>
    );
  }

  // Row Component (horizontal layout)
  if (component.component === "Row") {
    const { children, alignment, distribution, gap } = component;

    const alignmentMap: Record<string, string> = {
      start: "items-start",
      center: "items-center",
      end: "items-end",
      stretch: "items-stretch",
    };

    const distributionMap: Record<string, string> = {
      start: "justify-start",
      center: "justify-center",
      end: "justify-end",
      spaceBetween: "justify-between",
      spaceAround: "justify-around",
    };

    const alignClass = alignmentMap[alignment || "stretch"] || "items-stretch";
    const distClass = distributionMap[distribution || "start"] || "justify-start";
    const gapStyle = gap ? { gap: `${gap}px` } : { gap: "8px" };

    return (
      <div className={`flex flex-row ${alignClass} ${distClass}`} style={gapStyle}>
        {children.map((childId) => renderChild(childId))}
      </div>
    );
  }

  // Column Component (vertical layout)
  if (component.component === "Column") {
    const { children, alignment, distribution, gap } = component;

    const alignmentMap: Record<string, string> = {
      start: "items-start",
      center: "items-center",
      end: "items-end",
      stretch: "items-stretch",
    };

    const distributionMap: Record<string, string> = {
      start: "justify-start",
      center: "justify-center",
      end: "justify-end",
      spaceBetween: "justify-between",
      spaceAround: "justify-around",
    };

    const alignClass = alignmentMap[alignment || "stretch"] || "items-stretch";
    const distClass = distributionMap[distribution || "start"] || "justify-start";
    const gapStyle = gap ? { gap: `${gap}px` } : { gap: "16px" };

    return (
      <div className={`flex flex-col ${alignClass} ${distClass}`} style={gapStyle}>
        {children.map((childId) => renderChild(childId))}
      </div>
    );
  }

  // Card Component
  if (component.component === "Card") {
    const { id, child, action } = component;

    return (
      <Card
        className={action ? "cursor-pointer hover:bg-accent transition-colors" : ""}
        onClick={() => {
          if (action) {
            onAction(action, id);
          }
        }}
      >
        <CardContent className="p-4">
          {renderChild(child)}
        </CardContent>
      </Card>
    );
  }

  // Divider Component
  if (component.component === "Divider") {
    return <Separator className="my-4" />;
  }

  // Image Component
  if (component.component === "Image") {
    const { url, fit, altText } = component;
    const urlValue = resolveString(url, dataModel);
    const altValue = resolveString(altText, dataModel);

    const fitMap: Record<string, string> = {
      contain: "object-contain",
      cover: "object-cover",
      fill: "object-fill",
    };
    const fitClass = fitMap[fit || "contain"] || "object-contain";

    return (
      <img
        src={urlValue}
        alt={altValue}
        className={`max-w-full h-auto ${fitClass}`}
      />
    );
  }

  // ChoicePicker Component (select/radio group)
  if (component.component === "ChoicePicker") {
    const { id, label, options, selectedId, multiSelect, disabled } = component as any;
    const labelValue = resolveString(label, dataModel);
    const selectedValue = resolveString(selectedId, dataModel);
    const isDisabled = resolveBoolean(disabled, dataModel);
    const dataPath = typeof selectedId === "object" && selectedId.path ? selectedId.path : undefined;

    return (
      <div className="space-y-2">
        {labelValue && <Label>{labelValue}</Label>}
        <div className="space-y-2">
          {options?.map((option: any) => {
            const optionLabel = resolveString(option.label, dataModel);
            const optionDesc = option.description ? resolveString(option.description, dataModel) : "";
            const isSelected = selectedValue === option.id;

            return (
              <div
                key={option.id}
                className={`
                  p-3 rounded-md border cursor-pointer transition-colors
                  ${isSelected ? "border-primary bg-primary/10" : "border-muted hover:border-primary/50"}
                  ${isDisabled ? "opacity-50 cursor-not-allowed" : ""}
                `}
                onClick={() => {
                  if (!isDisabled && dataPath) {
                    onDataModelChange(dataPath, option.id);
                  }
                }}
              >
                <div className="flex items-center gap-2">
                  <div className={`
                    w-4 h-4 rounded-full border-2 flex items-center justify-center
                    ${isSelected ? "border-primary" : "border-muted-foreground"}
                  `}>
                    {isSelected && (
                      <div className="w-2 h-2 rounded-full bg-primary" />
                    )}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{optionLabel}</p>
                    {optionDesc && (
                      <p className="text-xs text-muted-foreground">{optionDesc}</p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Unsupported component - log and skip
  console.warn(`[A2UI] Unsupported component type:`, component.component);
  return null;
}

// =============================================================================
// Main Surface Renderer
// =============================================================================

export function A2UISurfaceRenderer({
  surfaceId,
  components,
  dataModel,
  onDataModelChange,
  onAction,
}: A2UISurfaceRendererProps): React.ReactElement | null {
  // Build component map for quick lookup
  const componentsMap = useMemo(() => {
    const map = new Map<string, A2UIComponent>();
    for (const comp of components) {
      map.set(comp.id, comp);
    }
    return map;
  }, [components]);

  // Find root component (A2UI v0.9: root component has id="root")
  const rootComponent = componentsMap.get("root");

  // Action handler wrapper
  const handleAction = useCallback(
    (action: A2UIAction, sourceComponentId: string) => {
      onAction(action, surfaceId, sourceComponentId);
    },
    [onAction, surfaceId]
  );

  if (!rootComponent) {
    console.warn(`[A2UI] No root component found in surface ${surfaceId}`);
    return null;
  }

  return (
    <div className="a2ui-surface" data-surface-id={surfaceId}>
      <ComponentRenderer
        component={rootComponent}
        componentsMap={componentsMap}
        dataModel={dataModel}
        onDataModelChange={onDataModelChange}
        onAction={handleAction}
      />
    </div>
  );
}

export default A2UISurfaceRenderer;
