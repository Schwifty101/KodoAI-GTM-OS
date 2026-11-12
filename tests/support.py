"""Shared test helpers."""

# Addresses and domains the db tests invent. Cleanup must delete ONLY these: real opt-outs and bounces share the reasons
# "opt-out reply" and "bounce", and a cleanup keyed on the reason alone once wiped imported production rows.
TEST_DOMAINS = [f"glow{i}.com" for i in range(300)] + ["gmail.com"]
TEST_EMAILS = [f"dana@glow{i}.com" for i in range(300)] + ["other@glow0.com", "dana@gmail.com"]


def purge_test_suppression(db) -> None:
    for i in range(0, len(TEST_EMAILS), 100):
        db.table("suppression").delete().in_("reason", ["opt-out reply", "bounce", "not-interested"]).in_("email", TEST_EMAILS[i : i + 100]).execute()
    for i in range(0, len(TEST_DOMAINS), 100):
        db.table("suppression").delete().in_("reason", ["opt-out reply", "bounce", "not-interested"]).in_("domain", TEST_DOMAINS[i : i + 100]).execute()
