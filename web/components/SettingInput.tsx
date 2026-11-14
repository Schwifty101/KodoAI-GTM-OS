import type { SettingField } from "@/lib/settings";

export function SettingInput({ f, vals, save }: { f: SettingField; vals: Record<string, unknown>; save: (f: SettingField, raw: string | boolean) => void }) {
  return (
    <label className="card">
      <div className="muted">{f.label}</div>
      {f.type === "bool" ? (
        <input type="checkbox" checked={vals[f.key] === true} onChange={(e) => save(f, e.target.checked)} />
      ) : (
        // key remounts the uncontrolled input after a save so it shows the stored value
        <input key={String(vals[f.key])} type={f.type === "date" ? "date" : f.type === "text" ? "text" : "number"} step={f.type === "float" ? "any" : 1}
          min={f.min} max={f.max} defaultValue={String(vals[f.key])} onBlur={(e) => e.target.value !== String(vals[f.key]) && save(f, e.target.value)} />
      )}
    </label>
  );
}
