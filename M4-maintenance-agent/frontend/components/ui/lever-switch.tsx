"use client";

import { cn } from "@/lib/utils";
import { useState } from "react";

interface LeverSwitchProps {
  defaultChecked?: boolean;
  onChange?: (checked: boolean) => void;
  label?: string;
  className?: string;
}

export const LeverSwitch = ({
  defaultChecked = false,
  onChange,
  label,
  className,
}: LeverSwitchProps) => {
  const [checked, setChecked] = useState(defaultChecked);

  const handleChange = () => {
    const next = !checked;
    setChecked(next);
    onChange?.(next);
  };

  return (
    <div className={cn("flex flex-col items-center gap-3", className)}>
      <div className="lever-container">
        <input
          className="lever-input"
          type="checkbox"
          checked={checked}
          onChange={handleChange}
          aria-label={label ?? "Toggle switch"}
        />
        <div className={cn("lever-handle-wrapper", checked && "lever-on")}>
          <div className="lever-handle">
            <div className="lever-handle-knob" />
            <div className="lever-handle-bar-wrapper">
              <div className="lever-handle-bar" />
            </div>
          </div>
        </div>
        <div className="lever-base">
          <div className="lever-base-inside">
            <span
              className={cn(
                "lever-base-label",
                checked ? "text-green-400" : "text-red-400"
              )}
            >
              {checked ? "ON" : "OFF"}
            </span>
          </div>
        </div>
      </div>
      {label && (
        <span className="text-sm font-medium text-muted-foreground">{label}</span>
      )}
    </div>
  );
};

export const Component = () => {
  return <LeverSwitch label="Power" />;
};
