-- 家人只读共享。在 Supabase 控制台 → SQL Editor 里整段粘贴运行一次（可重复运行）。
-- 流程：主人重新输入密码后生成一次性邀请码（只存哈希）→ 家人用自己的账号兑换 → 家人只能读，不能改。

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.shares (
  id bigint generated always as identity primary key,
  owner uuid not null default auth.uid() references auth.users (id) on delete cascade,
  owner_email text not null default lower(coalesce(auth.jwt() ->> 'email', '')),
  code_hash text,
  expires_at timestamptz not null default now() + interval '24 hours',
  viewer uuid references auth.users (id) on delete cascade,
  viewer_email text,
  created_at timestamptz not null default now()
);

alter table public.shares enable row level security;

drop policy if exists "owner manages" on public.shares;
create policy "owner manages" on public.shares for all
  using (owner = auth.uid()) with check (owner = auth.uid() and viewer is null);

drop policy if exists "viewer sees" on public.shares;
create policy "viewer sees" on public.shares for select using (viewer = auth.uid());

drop policy if exists "viewer leaves" on public.shares;
create policy "viewer leaves" on public.shares for delete using (viewer = auth.uid());

-- 家人兑换邀请码：只有这个函数能把自己写成 viewer
create or replace function public.redeem_share(code text)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  me uuid := auth.uid();
  row_id bigint;
  who text;
begin
  if me is null then
    raise exception '请先登录';
  end if;
  select id, owner_email into row_id, who from public.shares
   where code_hash = encode(extensions.digest(upper(trim(code)), 'sha256'), 'hex')
     and viewer is null and expires_at > now() and owner <> me
   limit 1;
  if row_id is null then
    raise exception '邀请码无效、已过期或已被使用';
  end if;
  update public.shares
     set viewer = me, viewer_email = lower(coalesce(auth.jwt() ->> 'email', '')), code_hash = null
   where id = row_id;
  return who;
end;
$$;

revoke all on function public.redeem_share(text) from public, anon;
grant execute on function public.redeem_share(text) to authenticated;

-- 被共享的人可以读主人的入金和成交（写入仍只能是本人，由原有的 "own rows" 规则保证）
drop policy if exists "shared read" on public.deposits;
create policy "shared read" on public.deposits for select using (
  exists (select 1 from public.shares s where s.owner = deposits.user_id and s.viewer = auth.uid()));

drop policy if exists "shared read" on public.trades;
create policy "shared read" on public.trades for select using (
  exists (select 1 from public.shares s where s.owner = trades.user_id and s.viewer = auth.uid()));
