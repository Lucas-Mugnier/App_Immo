-- ════════════════════════════════════════════════════════════════════════════
-- Immo-Radar / Alpestate — sécurité Supabase (version hybride)
-- À exécuter dans Supabase → SQL Editor. Idempotent (ré-exécutable).
--
-- Modèle :
--   • public.allowed_users = liste blanche des comptes invités (+ flag admin)
--   • bucket Storage « private-data » PRIVÉ : lecture réservée à la liste blanche
--     (écriture uniquement via la clé service_role du script local publish-data)
--   • public.corrections : lecture/proposition par les invités, modération admin
--   • À FAIRE AUSSI dans Authentication → Sign In / Providers :
--       décocher « Allow new users to sign up » (inscriptions fermées)
-- ════════════════════════════════════════════════════════════════════════════

-- 1. Liste blanche ────────────────────────────────────────────────────────────
create table if not exists public.allowed_users (
  email     text primary key,
  is_admin  boolean not null default false,
  added_at  timestamptz not null default now()
);
alter table public.allowed_users enable row level security;
-- Aucune policy : la table n'est ni lisible ni modifiable via l'API publique.
-- Gestion : SQL Editor (voir bas de fichier).

create or replace function public.is_allowed() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.allowed_users
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  )
$$;

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.allowed_users
    where is_admin and lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  )
$$;

revoke all on function public.is_allowed() from public, anon;
revoke all on function public.is_admin()   from public, anon;
grant execute on function public.is_allowed() to authenticated;
grant execute on function public.is_admin()   to authenticated;

-- 2. Bucket privé des annonces ────────────────────────────────────────────────
insert into storage.buckets (id, name, public)
values ('private-data', 'private-data', false)
on conflict (id) do update set public = false;

drop policy if exists "private-data: lecture invites" on storage.objects;
create policy "private-data: lecture invites" on storage.objects
  for select to authenticated
  using (bucket_id = 'private-data' and public.is_allowed());

-- 3. Corrections communautaires ───────────────────────────────────────────────
create table if not exists public.corrections (
  id              uuid primary key default gen_random_uuid(),
  listing_id      text not null,
  listing_url     text,
  listing_title   text,
  field           text not null,
  current_value   text,
  suggested_value text not null check (char_length(suggested_value) <= 500),
  comment         text check (char_length(comment) <= 2000),
  reporter_name   text check (char_length(reporter_name) <= 100),
  status          text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_at      timestamptz not null default now(),
  reviewed_at     timestamptz
);
create index if not exists corrections_listing_idx on public.corrections (listing_id);
alter table public.corrections enable row level security;

-- Supprime toute policy existante sur la table (y compris d'éventuelles policies
-- trop larges créées pendant le développement), puis recrée les bonnes.
do $$
declare p record;
begin
  for p in select policyname from pg_policies where schemaname = 'public' and tablename = 'corrections' loop
    execute format('drop policy %I on public.corrections', p.policyname);
  end loop;
end $$;

create policy "corrections: lecture invites" on public.corrections
  for select to authenticated using (public.is_allowed());

create policy "corrections: proposition invites" on public.corrections
  for insert to authenticated
  with check (public.is_allowed() and status = 'pending' and reviewed_at is null);

create policy "corrections: moderation admin" on public.corrections
  for update to authenticated
  using (public.is_admin()) with check (public.is_admin());

revoke all on public.corrections from anon;

-- 4. Gérer les invités ────────────────────────────────────────────────────────
-- insert into public.allowed_users (email, is_admin) values ('ton.email@exemple.com', true);
-- insert into public.allowed_users (email) values ('un.proche@exemple.com');
-- delete from public.allowed_users where email = 'un.proche@exemple.com';
-- Puis créer son compte : Authentication → Users → « Invite user ».
