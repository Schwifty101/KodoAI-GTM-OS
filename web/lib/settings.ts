// Mirror of DEFAULTS in gtm/settings_store.py: keep the key lists identical (scripts/verify.mts asserts it).
export type SettingField = { key: string; label: string; type: "int" | "float" | "bool" | "date" | "text"; group: string };

export const SETTING_FIELDS: SettingField[] = [
  { key: "monthly_budget_pkr", label: "Monthly budget (PKR)", type: "int", group: "Budget" },
  { key: "pkr_per_usd", label: "PKR per USD", type: "int", group: "Budget" },
  { key: "weekly_target", label: "Weekly owner target", type: "int", group: "Budget" },
  { key: "allow_paid_gemini", label: "Allow paid Gemini", type: "bool", group: "Google credit" },
  { key: "paid_gemini_monthly_cap_usd", label: "Paid Gemini monthly cap (USD)", type: "float", group: "Google credit" },
  { key: "credit_end_date", label: "Credit end date", type: "date", group: "Google credit" },
  { key: "credit_balance_usd", label: "Credit balance (USD)", type: "float", group: "Google credit" },
  { key: "credit_balance_as_of", label: "Balance as of", type: "date", group: "Google credit" },
  { key: "gemini_input_usd_per_m", label: "Gemini input USD per 1M tokens", type: "float", group: "API prices" },
  { key: "gemini_output_usd_per_m", label: "Gemini output USD per 1M tokens", type: "float", group: "API prices" },
  { key: "gemini_lite_input_usd_per_m", label: "Gemini Flash-Lite (replies) input USD per 1M tokens", type: "float", group: "API prices" },
  { key: "gemini_lite_output_usd_per_m", label: "Gemini Flash-Lite (replies) output USD per 1M tokens", type: "float", group: "API prices" },
  { key: "cap_apify_usd_day", label: "Apify USD per day", type: "float", group: "Daily caps" },
  { key: "cap_serper_queries_day", label: "Serper queries per day", type: "int", group: "Daily caps" },
  { key: "cap_gemini_usd_day", label: "Gemini USD per day", type: "float", group: "Daily caps" },
  { key: "cap_hunter_credits_day", label: "Hunter credits per day", type: "int", group: "Daily caps" },
  { key: "cap_prospeo_credits_day", label: "Prospeo credits per day", type: "int", group: "Daily caps" },
  { key: "cap_harvest_usd_day", label: "Harvest USD per day", type: "float", group: "Daily caps" },
  { key: "walk_schedule_enabled", label: "Daily walk schedule on (OFF by owner decision; turn on only when funded)", type: "bool", group: "Metro walk" },
  { key: "walk_hour_utc", label: "Walk hour (UTC)", type: "int", group: "Metro walk" },
  { key: "walk_tiles_per_run", label: "Tiles per walk run", type: "int", group: "Metro walk" },
  { key: "walk_queries", label: "Walk queries (ordered, comma separated)", type: "text", group: "Metro walk" },
  { key: "walk_max_places", label: "Max places per tile", type: "int", group: "Metro walk" },
  { key: "walk_escalate_at", label: "Escalate to next query at (fraction of max)", type: "float", group: "Metro walk" },
  { key: "fetch_fallback", label: "Fetch fallback on", type: "bool", group: "Metro walk" },
];

/** Python's `_ok`: int needs a whole number, float any number, bool a boolean, date a YYYY-MM-DD string, text a non-empty string. */
export function validSetting(f: SettingField, v: unknown): boolean {
  if (f.type === "text") return typeof v === "string" && v.trim() !== "";
  if (f.type === "bool") return typeof v === "boolean";
  if (f.type === "date") return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && !isNaN(Date.parse(v));
  return typeof v === "number" && Number.isFinite(v) && (f.type === "float" || Number.isInteger(v));
}
