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
  A2UIComponentType,
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
 */
function resolveString(value: StringOrPath | undefined, dataModel: Record<string, any>): string {
  if (!value) return "";
  if (value.literalString !== undefined) return value.literalString;
  if (value.path) return String(resolvePath(value.path, dataModel) ?? "");
  return "";
}

/**
 * Resolve BooleanOrPath to actual boolean value
 */
function resolveBoolean(value: BooleanOrPath | undefined, dataModel: Record<string, any>): boolean {
  if (!value) return false;
  if (value.literalBoolean !== undefined) return value.literalBoolean;
  if (value.path) return Boolean(resolvePath(value.path, dataModel));
  return false;
}

/**
 * Resolve NumberOrPath to actual number value
 */
function resolveNumber(value: NumberOrPath | undefined, dataModel: Record<string, any>): number {
  if (!value) return 0;
  if (value.literalNumber !== undefined) return value.literalNumber;
  if (value.path) return Number(resolvePath(value.path, dataModel) ?? 0);
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
  const { id, component: comp } = component;

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
  if ("Text" in comp) {
    const { text, styleHint } = comp.Text;
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
  if ("TextField" in comp) {
    const { label, text, placeholder, textFieldType, disabled } = comp.TextField;
    const labelValue = resolveString(label, dataModel);
    const textValue = resolveString(text, dataModel);
    const placeholderValue = resolveString(placeholder, dataModel);
    const isDisabled = resolveBoolean(disabled, dataModel);

    // Extract path for two-way binding
    const dataPath = text.path;

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
  if ("Button" in comp) {
    const { child, primary, disabled, action } = comp.Button;
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
  if ("CheckBox" in comp) {
    const { label, checked, disabled } = comp.CheckBox;
    const labelValue = resolveString(label, dataModel);
    const isChecked = resolveBoolean(checked, dataModel);
    const isDisabled = resolveBoolean(disabled, dataModel);
    const dataPath = checked.path;

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
  if ("Row" in comp) {
    const { children, alignment, distribution, gap } = comp.Row;

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
  if ("Column" in comp) {
    const { children, alignment, distribution, gap } = comp.Column;

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
  if ("Card" in comp) {
    const { child, action } = comp.Card;

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
  if ("Divider" in comp) {
    return <Separator className="my-4" />;
  }

  // Image Component
  if ("Image" in comp) {
    const { url, fit, altText } = comp.Image;
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

  // Unsupported component - log and skip
  console.warn(`[A2UI] Unsupported component type:`, Object.keys(comp)[0]);
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
