// Pure check (no env, no database): every settings group is either shown on Settings or deliberately hidden.
import assert from "node:assert";
import { SETTING_FIELDS, GROUPS, HIDDEN_GROUPS, validSetting } from "../lib/settings";
const shown = GROUPS.map(([g]) => g);
for (const f of SETTING_FIELDS) assert(shown.includes(f.group) || HIDDEN_GROUPS.includes(f.group), `group neither shown nor hidden: ${f.group}`);
assert(shown.includes("Sheet"), "Sheet group not shown");
assert(!HIDDEN_GROUPS.includes("Sheet"));
assert(shown.includes("Recontact"), "Recontact group not shown");
assert(!HIDDEN_GROUPS.includes("Recontact"));
const rc = Object.fromEntries(SETTING_FIELDS.filter((f) => f.group === "Recontact").map((f) => [f.key, f]));
assert.deepStrictEqual(Object.keys(rc), ["recontact_on", "recontact_days", "recontact_max_rounds", "recontact_hunter_allowance_credits"]);
assert.deepStrictEqual([rc.recontact_on.def, rc.recontact_days.def, rc.recontact_max_rounds.def, rc.recontact_hunter_allowance_credits.def], [false, 60, 3, 0]);
for (const k of ["recontact_days", "recontact_max_rounds"]) assert(!validSetting(rc[k], 0) && !validSetting(rc[k], -5) && validSetting(rc[k], 1), `${k} must reject below 1`);
console.log("settings_groups ok");
