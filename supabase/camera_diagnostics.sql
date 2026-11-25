-- 2026-11-25 追加: カメラの診断（ダッシュボードの「カメラの設定」表の「診断」欄）。Supabase の SQL Editor で1回実行する。
-- カメラが「付いたり消えたり」するとき、再起動しているのか（restarts・reset_reason）、
-- Wi-Fi が切れているのか（wifi_reconnects・offline_count）を見分けるための列。
-- 実行しなくてもサーバーは動く（列が無ければ診断を保存しないだけ）。
alter table public.cameras add column if not exists uptime_s         integer;      -- 起動してからの秒数（firmware 1.5.0〜）
alter table public.cameras add column if not exists reset_reason     text;         -- 前回の再起動の理由（poweron / brownout / panic / task_wdt など）
alter table public.cameras add column if not exists wifi_reconnects  integer;      -- 起動してから Wi-Fi がつながり直した回数
alter table public.cameras add column if not exists free_heap        integer;      -- 空きメモリ[バイト]
alter table public.cameras add column if not exists min_free_heap    integer;      -- 起動してからいちばん少なかった空きメモリ[バイト]
alter table public.cameras add column if not exists http_fails       integer;      -- 起動してからサーバーへの送信に失敗した回数
alter table public.cameras add column if not exists restarts         integer;      -- サーバーが数えた再起動の回数（uptime_s が減った回数）
alter table public.cameras add column if not exists last_restart_at  timestamptz;  -- 最後に再起動した時刻
alter table public.cameras add column if not exists offline_count    integer;      -- サーバーが数えた「停止」（60 秒より長く連絡なし）の回数
alter table public.cameras add column if not exists last_offline_at  timestamptz;  -- 最後に連絡が途切れ始めた時刻
alter table public.cameras add column if not exists last_offline_sec integer;      -- そのとき途切れていた秒数

-- 数え直したいとき（任意）:
-- update public.cameras set restarts = 0, offline_count = 0, last_restart_at = null, last_offline_at = null, last_offline_sec = null;
