-- Task 8: the clean pass needs the full Google categories list (primary category alone drops real med spas) and a closed flag.
alter table leads add column categories text[], add column closed boolean not null default false;
