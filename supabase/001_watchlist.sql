-- Shared private watchlist for the Fundamentals Desk and Sector Strength.
-- Add from either site (Fundamentals Desk: Stock page -> "Add to watchlist";
-- Sector Strength: the star next to a stock); both Watchlist tabs show the same list.
-- A stock stays until you delete it, or for 90 days after it was added from the
-- Fundamentals Desk / 30 days from Sector Strength (removed every night at 02:10 IST).
-- For stocks added from a Sector Strength setup, the evening check (19:40 IST,
-- Mon-Fri) records when price reached the buy level or the stop.
-- Safe to run more than once. Supabase -> SQL Editor -> New query -> paste -> Run.

create table if not exists public.fd_watchlist (
  id bigserial primary key,
  symbol text not null,
  name text,
  added_at timestamptz not null default now(),
  price_added double precision,          -- last close when it was added
  price_date date,                       -- the day of that close
  note text,
  owner text default (auth.jwt() ->> 'email'),
  unique (symbol)
);
alter table public.fd_watchlist add column if not exists source text not null default 'fd';      -- fd / ss
alter table public.fd_watchlist add column if not exists keep_days integer not null default 90;
alter table public.fd_watchlist add column if not exists setup text;                -- Breakout / Pullback / Tight base
alter table public.fd_watchlist add column if not exists grade text;
alter table public.fd_watchlist add column if not exists setup_date date;           -- day of the setup
alter table public.fd_watchlist add column if not exists buy double precision;
alter table public.fd_watchlist add column if not exists buy_is_trigger boolean default false;  -- "buy above" level
alter table public.fd_watchlist add column if not exists stop double precision;
alter table public.fd_watchlist add column if not exists buy_hit_on date;           -- filled by the evening check
alter table public.fd_watchlist add column if not exists stop_hit_on date;
alter table public.fd_watchlist add column if not exists last_close double precision;
alter table public.fd_watchlist add column if not exists last_date date;

alter table public.fd_watchlist enable row level security;
drop policy if exists "owner manages fd watchlist" on public.fd_watchlist;
create policy "owner manages fd watchlist" on public.fd_watchlist for all to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

-- nightly clean-up (02:10 IST = 20:40 UTC)
do $$ begin
  if exists (select 1 from cron.job where jobname = 'fd-watchlist-cleanup') then
    perform cron.unschedule('fd-watchlist-cleanup');
  end if;
end $$;
select cron.schedule('fd-watchlist-cleanup', '40 20 * * *',
  $$delete from public.fd_watchlist where added_at < now() - make_interval(days => keep_days)$$);

-- evening check of watchlist setups and My Trades (F&O Desk repo, cash-trades.yml):
-- 19:40 IST Monday to Friday (14:10 UTC), started by Supabase so it runs on time
do $$ begin
  if exists (select 1 from cron.job where jobname = 'cash-trades-evening') then
    perform cron.unschedule('cash-trades-evening');
  end if;
end $$;
select cron.schedule('cash-trades-evening', '10 14 * * 1-5',
  $$select public.dispatch_repo_workflow('fno-desk', 'cash-trades.yml')$$);
