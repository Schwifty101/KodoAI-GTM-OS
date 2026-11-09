-- Task 13: keep the exact draft text and the Touch 1 objective (Touch 2 and 3 reuse it) in the database.
alter table touches add column subject text, add column body text, add column objective text;
