-- ESP32 カメラ（firmware/esp32cam_uplink）の台帳と画像置き場。Supabase の SQL Editor で1回実行する。
-- カメラは 10 秒ごとに /api/camera_poll で生存を知らせ、誰かがダッシュボードで見ている間だけ
-- /api/camera_frame に JPEG を送る。画像は Storage の camera-frames バケットに「<camera_id>/latest.jpg」で上書きされる。
create table if not exists public.cameras (
  camera_id     text primary key,               -- firmware の CAMERA_ID（英数字・_・-、32 文字まで）
  label         text,                           -- 表示名
  distance_m    double precision,               -- 入口からの距離[m]（マップに表示する位置。任意）
  enabled       boolean not null default true,  -- false にすると画像を受け取らない
  fw            text,                           -- firmware のバージョン
  wifi_rssi     integer,                        -- カメラの Wi-Fi 受信強度
  width         integer,                        -- 最後に受けた画像の幅
  height        integer,                        -- 最後に受けた画像の高さ
  frame_bytes   integer,                        -- 最後に受けた画像の大きさ
  last_seen     timestamptz,                    -- 最後にカメラから連絡があった時刻
  last_frame_at timestamptz,                    -- 最後に画像を受けた時刻
  watch_until   timestamptz,                    -- この時刻までは「誰かが見ている」＝カメラが画像を送る
  created_at    timestamptz not null default now()
);

-- 画像置き場（非公開。サーバーが service role key で読み書きし、ログインした人にだけ返す）
insert into storage.buckets (id, name, public)
values ('camera-frames', 'camera-frames', false)
on conflict (id) do nothing;
