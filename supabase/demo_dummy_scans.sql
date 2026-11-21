-- デモ・確認用のダミーデータ: 「入口から 130m に立っている demo-01」の直近 60 秒分のスキャンを入れる。
-- Supabase の SQL Editor で、①〜③ をまとめて実行する（本番の DB に入る。装置 ID は必ず demo- で始める）。
--
--   ① ble_reports      … BLE のスキャン 2 秒ごと（ESP32 AP 表のうち fw が ble- で始まり、距離のあるビーコン）
--   ② wifi_reports_v2  … Wi-Fi のスキャン 5 秒ごと（AP位置設定の AP と、ESP32 AP 表のうち BLE でないもの）
--   ③ wifi_reports     … 装置の一覧・入退場のための今までの表に 1 行（BLE が見えれば BLE の上位2つ、無ければ Wi-Fi）
--
-- RSSI は scripts/demo_watch.py と同じ式: 1m での強さ − 10·n·log10(距離) ＋ ばらつき ±4dB。距離は高さの差 3m 込み。
--   BLE: -59dBm・n=2.2（-95 より弱いものは見えない）、Wi-Fi: -40dBm・n=2.0（-92 より弱いものは見えない）
-- 位置推定は直近 2 分のスキャンを使うので、マップで見るのは実行してから 1〜2 分の間だけ（もう一度実行すれば続く）。
-- 立っている位置・装置 ID を変えるときは、各文の先頭の params の 2 か所（'demo-01' と 130.0）を書き換える。
-- 動き回る人を続けて入れたいときは scripts/demo_watch.py（docs/AI_WORKFLOW.md §5）。

-- ① BLE のスキャン
with params as (select 'demo-01'::text as device_id, 130.0::float8 as x),
ble as (
  select upper(mac) as mac, distance_m::float8 as d
  from public.ap_nodes
  where enabled is not false and distance_m is not null and coalesce(fw, '') like 'ble-%'
),
times as (
  select now() - make_interval(secs => s::float8) as t from generate_series(0, 58, 2) as s
),
seen as (
  select times.t, ble.mac,
         round(-59 - 22 * log(sqrt((params.x - ble.d) ^ 2 + 9)) + (random() * 8 - 4))::int as rssi
  from times cross join ble cross join params
),
ranked as (
  select t, mac, rssi, row_number() over (partition by t order by rssi desc) as rn
  from seen where rssi >= -95
)
insert into public.ble_reports (device_id, scanned_at, created_at, mac01, rssi01, mac02, rssi02, mac03, rssi03)
select (select device_id from params), t, t,
       max(mac) filter (where rn = 1), max(rssi) filter (where rn = 1),
       max(mac) filter (where rn = 2), max(rssi) filter (where rn = 2),
       max(mac) filter (where rn = 3), max(rssi) filter (where rn = 3)
from ranked where rn <= 3
group by t;

-- ② Wi-Fi のスキャン
with params as (select 'demo-01'::text as device_id, 130.0::float8 as x),
wifi as (
  -- 同じ MAC が両方の表にあれば ESP32 AP の方を使う（サーバーの load_ap_map と同じ）
  select distinct on (mac) mac, d from (
    select upper(mac) as mac, distance_m::float8 as d, 1 as pri
    from public.ap_nodes
    where enabled is not false and distance_m is not null and coalesce(fw, '') not like 'ble-%'
    union all
    select upper(mac),
           coalesce(distance_m, (array[0, 100, 200, 300, 400, 500])[position + 1])::float8, 2
    from public.ap_positions
  ) u
  order by mac, pri
),
times as (
  select now() - make_interval(secs => s::float8) as t from generate_series(0, 55, 5) as s
),
seen as (
  select times.t, wifi.mac,
         round(-40 - 20 * log(sqrt((params.x - wifi.d) ^ 2 + 9)) + (random() * 8 - 4))::int as rssi
  from times cross join wifi cross join params
  where wifi.d is not null
),
ranked as (
  select t, mac, rssi, row_number() over (partition by t order by rssi desc) as rn
  from seen where rssi >= -92
)
insert into public.wifi_reports_v2 (device_id, scanned_at, created_at, mac01, rssi01, mac02, rssi02, mac03, rssi03)
select (select device_id from params), t, t,
       max(mac) filter (where rn = 1), max(rssi) filter (where rn = 1),
       max(mac) filter (where rn = 2), max(rssi) filter (where rn = 2),
       max(mac) filter (where rn = 3), max(rssi) filter (where rn = 3)
from ranked where rn <= 3
group by t;

-- ③ 今までの wifi_reports に 1 行（①② の最新のスキャンから。BLE が見えていれば BLE の上位2つ）
with params as (select 'demo-01'::text as device_id),
latest as (
  select mac01, mac02, 1 as pri from public.ble_reports
  where device_id = (select device_id from params) order by created_at desc limit 1
),
latest_wifi as (
  select mac01, mac02, 2 as pri from public.wifi_reports_v2
  where device_id = (select device_id from params) order by created_at desc limit 1
),
pick as (
  select mac01, mac02 from (select * from latest union all select * from latest_wifi) x
  where mac01 is not null order by pri limit 1
)
insert into public.wifi_reports (device_id, mac01, mac02)
select (select device_id from params), mac01, mac02 from pick;

-- 入ったか確かめる
select 'ble_reports' as 表, count(*) as 行数 from public.ble_reports where device_id like 'demo-%'
union all
select 'wifi_reports_v2', count(*) from public.wifi_reports_v2 where device_id like 'demo-%'
union all
select 'wifi_reports', count(*) from public.wifi_reports where device_id like 'demo-%';


-- ===== 消すとき（デモが終わったら、この下だけを選んで実行） =====
-- delete from public.ble_reports          where device_id like 'demo-%';
-- delete from public.wifi_reports_v2      where device_id like 'demo-%';
-- delete from public.wifi_reports         where device_id like 'demo-%';
-- delete from public.device_instructions  where device_id like 'demo-%';
-- delete from public.device_segment_state where device_id like 'demo-%';
-- delete from public.entry_current        where device_id like 'demo-%';
-- delete from public.entry_log            where device_id like 'demo-%';
-- delete from public.position_eval        where device_id like 'demo-%';
