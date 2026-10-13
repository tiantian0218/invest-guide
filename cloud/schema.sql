-- 在 Supabase 控制台 → SQL Editor 里整段粘贴运行一次。
-- 每行数据带 user_id，行级安全（RLS）保证每个用户只能读写自己的记录。

create table if not exists public.deposits (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  date date not null,
  cny numeric not null default 0,
  usd numeric not null,
  note text not null default '',
  deleted boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.trades (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  date date not null,
  ticker text not null,
  shares numeric not null,
  price_usd numeric not null,
  fee_usd numeric not null default 0,
  note text not null default '',
  deleted boolean not null default false,
  created_at timestamptz not null default now()
);

alter table public.deposits enable row level security;
alter table public.trades enable row level security;

drop policy if exists "own rows" on public.deposits;
create policy "own rows" on public.deposits for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "own rows" on public.trades;
create policy "own rows" on public.trades for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

create index if not exists deposits_user on public.deposits (user_id, date);
create index if not exists trades_user on public.trades (user_id, date);
