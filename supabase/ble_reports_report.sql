-- 2026-11-22: BLE のスキャンでも通報を受け取る。Supabase の SQL Editor で1回実行する。
-- ウォッチは wifi_reports_v2 と ble_reports の両方に report を送り、サーバーは後から届いた方の値を使う
-- （api/app.py の report_of）。
-- この列は空（null）を許す。空の行は「通報を送っていない」とみなし、wifi_reports_v2 の値を使う
-- （BLE 側に通報を送らないウォッチでも、Wi-Fi 側の通報が「なし」で上書きされないように）。
alter table public.ble_reports add column if not exists report boolean;
