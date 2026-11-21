-- 2026-11-22: ウォッチの送り先を wifi_reports_v2 / ble_reports に一本化する（旧 wifi_reports はサーバーが読まない）。
-- Supabase の SQL Editor で1回実行する。

-- 通報（今まで wifi_reports.report にあったもの）を Wi-Fi のスキャンと一緒に受け取る。
-- 押されている間は true を送り続け、解除したら false。サーバーは装置ごとに最新の行の値を見る
alter table public.wifi_reports_v2 add column if not exists report boolean not null default false;

-- 画面のマップの即時更新（今までは latest_wifi_reports を見張っていた）。
-- wifi_reports_v2 を Realtime の対象に入れる（入っていれば何もしない）
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'wifi_reports_v2'
  ) then
    alter publication supabase_realtime add table public.wifi_reports_v2;
  end if;
end $$;

-- 注意:
-- - 旧 wifi_reports の report 列は消さない（今のウォッチがまだ書き込んでいるので、消すと書き込みが失敗する）。
--   ウォッチが新しい表だけに送るようになったら、wifi_reports と latest_wifi_reports は片付けてよい。
-- - Realtime は anon キーで動くので、wifi_reports_v2 を anon が SELECT できないと即時更新は届かない（5 秒ごとの更新は動く）。
-- - ウォッチ（anon キー）が wifi_reports_v2 / ble_reports に INSERT できる RLS ポリシーも必要。
