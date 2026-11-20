-- 位置推定 ⑥（Wi-Fi と BLE をそれぞれ向いた計算で合わせる）の比較記録の列。Supabase の SQL Editor で1回実行する。
-- （無くても記録はできるが、⑥ の値が残らない）
alter table public.position_eval add column if not exists fusion_series double precision;
