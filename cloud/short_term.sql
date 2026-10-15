-- 短线模拟盘快照：本机每天更新后上传一份，网站「我的账户」里展示。在 SQL Editor 运行一次（可重复运行）。
create table if not exists public.paper (
  user_id uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.paper enable row level security;

drop policy if exists "own rows" on public.paper;
create policy "own rows" on public.paper for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "shared read" on public.paper;
create policy "shared read" on public.paper for select using (
  exists (select 1 from public.shares s where s.owner = paper.user_id and s.viewer = auth.uid()));
