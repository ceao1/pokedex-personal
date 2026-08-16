insert into storage.buckets (id, name, public)
values ('card-photos', 'card-photos', false)
on conflict (id) do nothing;
