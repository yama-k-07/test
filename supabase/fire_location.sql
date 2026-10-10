-- 火災位置機能のテーブル（2026-10-10 追加）
-- Supabase の SQL Editor で1回実行する。既存テーブルには触らない。

-- 管理マップで指定した火災位置（常に id=1 の1行だけ使う）
create table if not exists public.fire_location (
  id          integer primary key default 1 check (id = 1),
  active      boolean not null default false,
  distance_m  double precision,          -- 入口からの距離[m]（AP1=1m 〜 AP11=11m）
  updated_at  timestamptz not null default now()
);

-- ウォッチごとの「自分から見た火災の方向」。サーバー（api/app.py）が書き、ウォッチが自分の行を読む。
create table if not exists public.device_fire_alerts (
  device_id   text primary key,
  fire_active boolean not null default false,
  direction   text check (direction in ('inward', 'outward', 'near', 'unknown')),
                                         -- inward=奥側 / outward=入口側 / near=すぐ近く / unknown=自分の位置が不明
  distance_m  double precision,          -- 自分から火災までの距離[m]（推定。誤差 1〜2m）
  message     text,                      -- そのまま画面に出せる文（例「火災: 奥 約4m」）
  approx      boolean not null default false, -- true=自分の位置がエリア単位でしか分かっていない
  updated_at  timestamptz not null default now()
);

-- ウォッチが Realtime で変更を受け取れるようにする（ポーリングで読むなら不要）
alter publication supabase_realtime add table public.device_fire_alerts;

-- ウォッチが anon key で読む場合は RLS で読み取りだけ許可する（service role key なら不要）
-- alter table public.device_fire_alerts enable row level security;
-- create policy "watch can read fire alerts" on public.device_fire_alerts for select using (true);
