-- AP位置設定（現場の Wi-Fi AP）に「入口からの距離」を持たせる。Supabase の SQL Editor で1回実行する。
-- 今までは位置番号 0〜5 が距離（0〜500m、100m 間隔）を表していた。この列が入ると、画面で MAC と距離を入れるだけで
-- 何台でも追加できる（位置番号は自動で振る）。空の行は今までどおり位置番号から距離を決める（api/app.py の load_ap_position_rows）。
alter table public.ap_positions add column if not exists distance_m double precision;

-- 今ある行に、位置番号の距離を入れておく（画面に今の距離が出るように）
update public.ap_positions set distance_m = (array[0, 100, 200, 300, 400, 500])[position + 1]
where distance_m is null and position between 0 and 5;
