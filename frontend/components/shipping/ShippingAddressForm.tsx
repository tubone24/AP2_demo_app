"use client";

import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot } from "lucide-react";

interface ShippingFormField {
  name: string;
  label: string;
  type: string;
  required: boolean;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
}

interface ShippingAddressFormProps {
  fields: ShippingFormField[];
  onSubmit: (data: Record<string, string>) => void;
}

export function ShippingAddressForm({ fields, onSubmit }: ShippingAddressFormProps) {
  // フォームデータの状態管理
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [isValid, setIsValid] = useState(false);

  // 必須フィールドがすべて入力されているかチェック
  useEffect(() => {
    const requiredFields = fields.filter((field) => field.required);
    const allRequiredFilled = requiredFields.every(
      (field) => formData[field.name] && formData[field.name].trim() !== ""
    );
    setIsValid(allRequiredFilled);
  }, [formData, fields]);

  // フィールド値の変更ハンドラ
  const handleFieldChange = (fieldName: string, value: string) => {
    setFormData((prev) => ({
      ...prev,
      [fieldName]: value,
    }));
  };

  // フォーム送信ハンドラ
  const handleSubmit = () => {
    if (!isValid) return;
    onSubmit(formData);
  };

  return (
    <div className="mb-4">
      <div className="flex gap-3">
        <Avatar className="w-8 h-8 flex-shrink-0">
          <AvatarFallback className="bg-green-500">
            <Bot className="w-4 h-4 text-white" />
          </AvatarFallback>
        </Avatar>
        <div className="w-full max-w-[600px]">
          <Card>
            <CardContent className="p-4 space-y-3">
              {fields.map((field) => (
                <div key={field.name}>
                  <label className="block text-sm font-medium mb-1">
                    {field.label}
                    {field.required && <span className="text-red-500 ml-1">*</span>}
                  </label>
                  {field.type === "select" ? (
                    <select
                      className="w-full px-3 py-2 border rounded-md"
                      value={formData[field.name] || ""}
                      onChange={(e) => handleFieldChange(field.name, e.target.value)}
                    >
                      <option value="">選択してください</option>
                      {field.options?.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={field.type}
                      placeholder={field.placeholder}
                      className="w-full px-3 py-2 border rounded-md"
                      required={field.required}
                      value={formData[field.name] || ""}
                      onChange={(e) => handleFieldChange(field.name, e.target.value)}
                    />
                  )}
                </div>
              ))}
              <button
                onClick={handleSubmit}
                disabled={!isValid}
                className={`w-full px-4 py-2 rounded-md transition-colors ${
                  isValid
                    ? "bg-primary text-primary-foreground hover:bg-primary/90"
                    : "bg-gray-300 text-gray-500 cursor-not-allowed"
                }`}
              >
                配送先を確定
              </button>
              {!isValid && (
                <p className="text-xs text-red-500 text-center">
                  必須項目をすべて入力してください
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
