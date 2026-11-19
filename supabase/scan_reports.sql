-- ウォッチのスキャン結果（RSSI 上位3つ）と、位置推定の方式の設定・比較記録。Supabase の SQL Editor で1回実行する。
-- ウォッチは Wi-Fi のスキャンを wifi_reports_v2、BLE のスキャンを ble_reports に 1 回 1 行で入れる（docs/WATCH_SCAN_REPORTS.md）。
-- 移行中は今までの wifi_reports にも送り続ける（装置の一覧・入退場・通報は wifi_reports を見ているため）。

-- Wi-Fi のスキャン 1 回分。mac01 が最も強い（rssi01 が最大）
create table if not exists public.wifi_reports_v2 (
  id          bigint generated always as identity primary key,
  device_id   text not null,
  scanned_at  timestamptz,                         -- スキャンした時刻（ウォッチの時計）。無ければ created_at を使う
  created_at  timestamptz not null default now(), -- 届いた時刻
  mac01 text, rssi01 integer,                      -- RSSI[dBm]（例 -62）
  mac02 text, rssi02 integer,
  mac03 text, rssi03 integer
);
create index if not exists wifi_reports_v2_created_idx on public.wifi_reports_v2 (created_at desc);
create index if not exists wifi_reports_v2_device_idx on public.wifi_reports_v2 (device_id, created_at desc);

-- BLE のスキャン 1 回分（名前が MAMOTCHI- で始まるビーコンだけ）。列は wifi_reports_v2 と同じ
create table if not exists public.ble_reports (
  id          bigint generated always as identity primary key,
  device_id   text not null,
  scanned_at  timestamptz,
  created_at  timestamptz not null default now(),
  mac01 text, rssi01 integer,
  mac02 text, rssi02 integer,
  mac03 text, rssi03 integer
);
create index if not exists ble_reports_created_idx on public.ble_reports (created_at desc);
create index if not exists ble_reports_device_idx on public.ble_reports (device_id, created_at desc);

-- 画面で選んだ位置推定の方式（1行だけ: id=1）。
-- top2_basic=① 上位2つ＋今までの平滑化 / top2_series=② 上位2つ＋時系列 / rssi_basic=③ RSSI の差 / rssi_series=④ RSSI の差＋時系列
create table if not exists public.position_settings (
  id         integer primary key default 1 check (id = 1),
  method     text not null default 'top2_basic',
  updated_at timestamptz not null default now()
);
insert into public.position_settings (id, method) values (1, 'top2_basic') on conflict (id) do nothing;

-- 現地での比較記録。決まった地点に立って「記録」を押すと、その時の ①〜④ の推定を正しい位置と一緒に残す
create table if not exists public.position_eval (
  id              bigint generated always as identity primary key,
  created_at      timestamptz not null default now(),
  device_id       text not null,
  true_distance_m double precision not null,   -- 本当に立っていた位置（入口からの m）
  method_selected text,                        -- その時に画面で使っていた方式
  sources         text,                        -- 使ったスキャン（wifi / ble / wifi_legacy）
  top2_basic      double precision,
  top2_series     double precision,
  rssi_basic      double precision,
  rssi_series     double precision,
  note            text
);

-- RLS: どの表も Flask が service role key で読み書きする。ウォッチ（anon key）が書き込めるように、
-- 既存の wifi_reports と同じポリシーを wifi_reports_v2 / ble_reports にも付けること（今の設定は Supabase の画面で確認）。
