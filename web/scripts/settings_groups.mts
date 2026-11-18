// Pure check (no env, no database): every settings group is either shown on Settings or deliberately hidden.
import assert from "node:assert";
import { SETTING_FIELDS, GROUPS, HIDDEN_GROUPS } from "../lib/settings";
const shown = GROUPS.map(([g]) => g);
for (const f of SETTING_FIELDS) assert(shown.includes(f.group) || HIDDEN_GROUPS.includes(f.group), `group neither shown nor hidden: ${f.group}`);
assert(shown.includes("Sheet"), "Sheet group not shown");
assert(!HIDDEN_GROUPS.includes("Sheet"));
console.log("settings_groups ok");
