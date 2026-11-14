// Mirror of DEFAULTS in gtm/settings_store.py: scripts/verify.mts asserts keys and defaults equal the Python ones.
export type SettingField = { key: string; label: string; type: "int" | "float" | "bool" | "date" | "text"; group: string; def: boolean | number | string; min?: number; max?: number };

export const SETTING_FIELDS: SettingField[] = [
  { key: "monthly_budget_pkr", label: "Monthly budget (PKR)", type: "int", group: "Budget", def: 25000 },
  { key: "pkr_per_usd", label: "PKR per USD", type: "int", group: "Budget", def: 276 },
  { key: "weekly_target", label: "Weekly owner target", type: "int", group: "Budget", def: 200 },
  { key: "allow_paid_gemini", label: "Allow paid Gemini", type: "bool", group: "Google credit", def: false },
  { key: "paid_gemini_monthly_cap_usd", label: "Paid Gemini monthly cap (USD)", type: "float", group: "Google credit", def: 0 },
  { key: "credit_end_date", label: "Credit end date", type: "date", group: "Google credit", def: "2027-02-09" },
  { key: "credit_balance_usd", label: "Credit balance (USD)", type: "float", group: "Google credit", def: 298 },
  { key: "credit_balance_as_of", label: "Balance as of", type: "date", group: "Google credit", def: "2026-11-12" },
  { key: "gemini_input_usd_per_m", label: "Gemini input USD per 1M tokens", type: "float", group: "API prices", def: 1.5 },
  { key: "gemini_output_usd_per_m", label: "Gemini output USD per 1M tokens", type: "float", group: "API prices", def: 9 },
  { key: "gemini_lite_input_usd_per_m", label: "Gemini Lite input USD per 1M tokens", type: "float", group: "API prices", def: 0.25 },
  { key: "gemini_lite_output_usd_per_m", label: "Gemini Lite output USD per 1M tokens", type: "float", group: "API prices", def: 1.5 },
  { key: "cap_apify_usd_day", label: "Apify USD per day", type: "float", group: "Daily caps", def: 2 },
  { key: "cap_serper_queries_day", label: "Serper queries per day", type: "int", group: "Daily caps", def: 700 },
  { key: "cap_gemini_usd_day", label: "Gemini USD per day", type: "float", group: "Daily caps", def: 5 },
  { key: "cap_hunter_credits_day", label: "Hunter credits per day", type: "int", group: "Daily caps", def: 100 },
  { key: "cap_prospeo_credits_day", label: "Prospeo credits per day", type: "int", group: "Daily caps", def: 20 },
  { key: "cap_harvest_usd_day", label: "Harvest USD per day", type: "float", group: "Daily caps", def: 0.5 },
  { key: "cap_serper_maps_credits_day", label: "Serper Maps credits per day", type: "int", group: "Daily caps", def: 300 },
  { key: "scrape_provider", label: "Scrape provider (apify or serper)", type: "text", group: "Scrape walk", def: "apify" },
  { key: "walk_schedule_enabled", label: "Run daily schedule", type: "bool", group: "Scrape walk", def: false },
  { key: "walk_hour_utc", label: "Schedule hour (UTC, 0-23)", type: "int", group: "Scrape walk", def: 13, min: 0, max: 23 },
  { key: "walk_tiles_per_run", label: "Tiles per run", type: "int", group: "Scrape walk", def: 3, min: 1, max: 20 },
  { key: "walk_queries", label: "Search terms (comma separated, tried in order)", type: "text", group: "Scrape walk", def: "med spa,aesthetics clinic" },
  { key: "walk_max_places", label: "Max places per query", type: "int", group: "Scrape walk", def: 40, min: 1, max: 200 },
  { key: "walk_escalate_at", label: "Go to next term when a query returned at least this share of the cap (0-1)", type: "float", group: "Scrape walk", def: 0.8, min: 0, max: 1 },
  { key: "fetch_fallback", label: "Read blocked pages through a paid fallback", type: "bool", group: "Page fetching", def: true },
];

/** Python's `_ok` plus the ranges: int needs a whole number, float any number, bool a boolean, date a YYYY-MM-DD string, text a non-empty string. */
export function validSetting(f: SettingField, v: unknown): boolean {
  if (f.type === "text") return typeof v === "string" && v.trim() !== "";
  if (f.type === "bool") return typeof v === "boolean";
  if (f.type === "date") return typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && !isNaN(Date.parse(v));
  return typeof v === "number" && Number.isFinite(v) && (f.type === "float" || Number.isInteger(v))
    && (f.min === undefined || v >= f.min) && (f.max === undefined || v <= f.max);
}

export const settingDefaults = (): Record<string, unknown> => Object.fromEntries(SETTING_FIELDS.map((f) => [f.key, f.def]));
