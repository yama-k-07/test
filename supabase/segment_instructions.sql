-- AP の区間（0〜100m など）ごとのまとめた指示。Supabase の SQL Editor で1回実行する。
-- 区間の指示は device_instructions（個別指示）としてウォッチに送るので、ウォッチ側は変わらない（api/app.py の apply_segment_instructions）。

-- 区間ごとの指示。segment_key は「始まり-終わり」の距離（例 '0-100'）。AP の配置が変わると区間も変わる
create table if not exists public.segment_instructions (
  segment_key text primary key,
  start_m     double precision not null,
  end_m       double precision not null,
  instruction text not null default 'none',   -- none / wait / inward / outward（device_instructions と同じ）
  updated_at  timestamptz not null default now()
);

-- 各ウォッチが最後にいた区間と、そのとき送った区間の指示の時刻（区間に入ったときに1回だけ送るため）
create table if not exists public.device_segment_state (
  device_id          text primary key,
  segment_key        text,
  segment_updated_at timestamptz,
  updated_at         timestamptz not null default now()
);

-- 位置推定 ⑤（Wi-Fi だけ・上位3つの当てはめ）の比較記録の列（supabase/scan_reports.sql を実行済みの DB 向け）
alter table public.position_eval add column if not exists wifi3_series double precision;
