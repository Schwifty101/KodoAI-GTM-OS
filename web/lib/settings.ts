// Mirror of DEFAULTS in gtm/settings_store.py: scripts/verify.mts asserts keys and defaults equal the Python ones.
export type SettingField = { key: string; label: string; type: "int" | "float" | "bool" | "date" | "text"; group: string; def: boolean | number | string | Record<string, number>; min?: number; max?: number; readonly?: boolean };

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
  { key: "walk_yield_order", label: "Order tiles by past yield", type: "bool", group: "Scrape walk", def: true },
  { key: "clean_category_strict", label: "Clean: require the Medical spa category", type: "bool", group: "Scrape walk", def: true },
  { key: "send_anytime", label: "REHEARSAL ONLY: send outside the Mon-Fri 9-16 window (leave off for real sending)", type: "bool", group: "Sending", def: false },
  { key: "sending_on", label: "Sending on", type: "bool", group: "Sending", def: false },
  { key: "sheet_id", label: "Google Sheet ID", type: "text", group: "Sheet", def: "" },
  { key: "sheet_queue_size", label: "Leads queued to the sheet per day", type: "int", group: "Sheet", def: 5, min: 0, max: 50 },
  { key: "sheet_queue_on", label: "Daily sheet queue on", type: "bool", group: "Sheet", def: false },
  { key: "sheet_queue_hour_utc", label: "Sheet queue hour (UTC, 0-23)", type: "int", group: "Sheet", def: 13, min: 0, max: 23 },
  { key: "sheet_writeback_on", label: "Write status colours back to the sheet", type: "bool", group: "Sheet", def: false },
  { key: "import_hunter_allowance_credits", label: "Hunter credits allowed for sheet imports", type: "float", group: "Sheet", def: 0, min: 0 },
  { key: "autopilot_on", label: "Autopilot on", type: "bool", group: "Autopilot", def: false, readonly: true },
  { key: "autopilot_limit_usd", label: "Autopilot spend limit (USD, 0 = no limit)", type: "float", group: "Autopilot", def: 2, min: 0 },
  { key: "autopilot_target", label: "Autopilot target leads per batch", type: "int", group: "Autopilot", def: 100, min: 1 },
  { key: "autopilot_state", label: "Autopilot state", type: "text", group: "Autopilot", def: "off", readonly: true },
  { key: "autopilot_started_at", label: "Autopilot started at", type: "text", group: "Autopilot", def: "", readonly: true },
  { key: "batch_base", label: "Leads already in a batch outside the OS (JSON)", type: "text", group: "Autopilot", def: { "3": 32 }, readonly: true },
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

// Groups shown on the Settings page, with a hint each.
export const GROUPS: [string, string][] = [
  ["Budget", "Monthly budget and exchange rate used in the cost views."],
  ["Google credit", "Free-trial credit: it ends on the date below unless the full account is activated first."],
  ["API prices", "Third-party prices, unconfirmed; they only change what the cost views show."],
  ["Daily caps", "Each cap is in the provider's own unit and is checked before every paid call; 0 blocks the provider."],
  ["Page fetching", ""],
  ["Autopilot", "Runs the pipeline passes by itself within the spend limit. Start and Pause live on Batches; the state and start time are written by the controller."],
  ["Sheet", "The MedSpa sheet: its id, the daily ContactOut queue and the colour write-back. Both switches stay off until the owner turns them on; the Hunter allowance is a one-off lifetime budget for the sheet import and defaults to 0 (nothing can be spent)."],
];
// Shown on their own pages, never on Settings.
export const HIDDEN_GROUPS = ["Scrape walk", "Sending"];
