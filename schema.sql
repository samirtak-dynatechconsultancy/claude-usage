-- Run this once in the Supabase SQL editor (Dashboard -> SQL -> New query).
-- Creates the table the collector writes to, and lets the publishable
-- (anon) key INSERT rows.

create table if not exists public.claude_usage (
  id                  bigint generated always as identity primary key,
  captured_at         timestamptz not null default now(),
  email               text,
  org_id              text,
  session_pct         numeric,      -- 5-hour bucket %
  weekly_pct          numeric,      -- 7-day bucket %
  five_hour_resets_at timestamptz,
  seven_day_resets_at timestamptz,
  host                text,         -- machine name (which user's PC)
  os_user             text          -- Windows username
);

-- Helpful for "latest per user" queries.
create index if not exists claude_usage_email_time_idx
  on public.claude_usage (email, captured_at desc);

-- RLS: allow INSERT only (no read/update/delete) from the client key.
-- NOTE: policy applies to ALL roles (no `to` clause = `public`) because the
-- new `sb_publishable_` keys don't reliably match a `to anon` policy.
alter table public.claude_usage enable row level security;

drop policy if exists "anon can insert usage" on public.claude_usage;
drop policy if exists "anyone can insert usage" on public.claude_usage;
create policy "anyone can insert usage"
  on public.claude_usage
  for insert
  with check (true);

-- NOTE: with only this policy, the anon key cannot SELECT the data back.
-- View it in the Supabase dashboard, or read it with the service_role key
-- from a trusted backend / dashboard (never ship service_role to clients).
