-- ESP32-S3 で作った AP の台帳（firmware/esp32s3_ap）。Supabase の SQL Editor で1回実行する。
-- ESP32 が /api/ap_heartbeat を送ると行が自動で作られ、30 秒ごとに稼働情報が更新される。
-- 位置推定に使う distance_m（入口からの m）は管理画面の「ESP32 AP」で設定する（firmware の値は初期値）。
create table if not exists public.ap_nodes (
  mac           text primary key,            -- softAP の BSSID（AA:BB:CC:DD:EE:FF、大文字）。ウォッチの mac01/mac02 と照合する
  label         text,                        -- 表示名（例 A050）
  distance_m    double precision,            -- 入口からの距離[m]。null の間は位置推定に使わない
  enabled       boolean not null default true, -- false にすると位置推定から外す（故障・撤去時）
  fw            text,                        -- firmware のバージョン
  uptime_s      bigint,                      -- 起動からの秒数（再起動の検知用）
  sta_count     integer,                     -- softAP に接続中の端末数（通常 0。ウォッチは接続せずスキャンするだけ）
  tx_power_dbm  double precision,            -- 送信出力
  channel       integer,                     -- softAP のチャンネル
  uplink_rssi   integer,                     -- 上り回線（現場 Wi-Fi）の受信強度。heartbeat が途切れる原因の切り分け用
  last_seen     timestamptz,                 -- 最後に heartbeat を受けた時刻
  created_at    timestamptz not null default now()
);
