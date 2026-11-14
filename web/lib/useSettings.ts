import { useCallback, useEffect, useState } from "react";
import { supabase } from "./supabase";
import { saveSetting } from "./actions";
import { settingDefaults, type SettingField } from "./settings";

/** Settings table over the built-in defaults; `save` validates through saveSetting and reports a rejection in `err`. */
export function useSettings(ready: boolean) {
  const [vals, setVals] = useState<Record<string, unknown>>(settingDefaults);
  const [err, setErr] = useState("");
  const reload = useCallback(async () => {
    const { data, error } = await supabase.from("settings").select("key,value");
    if (error) return setErr(error.message);
    setVals({ ...settingDefaults(), ...Object.fromEntries((data ?? []).map((r) => [r.key, r.value])) });
  }, []);
  useEffect(() => { if (ready) reload(); }, [ready, reload]);
  const save = async (f: SettingField, raw: string | boolean) => {
    try {
      await saveSetting(f.key, f.type === "int" || f.type === "float" ? (raw === "" ? NaN : Number(raw)) : raw);
      setErr("");
      await reload();
    } catch (e) { setErr((e as Error).message); }
  };
  return { vals, reload, save, err };
}
