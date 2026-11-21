-- デモ・確認用のダミーデータ: 「demo-01」がトンネルに立っている直近 60 秒分のスキャンを入れる。
-- 立つ位置は、BLE ビーコンがあれば「いちばん手前のビーコン + 5m」（BLE は約 40m より遠いと見えないため）、
-- 無ければ 130m。位置を決めたいときは ① ② の params の null を数字にする（2 か所とも同じ値に）。
-- Supabase の SQL Editor で、①② をまとめて実行する（本番の DB に入る。装置 ID は必ず demo- で始める）。
--
--   ① ble_reports      … BLE のスキャン 2 秒ごと（ESP32 AP 表のうち fw が ble- で始まり、距離のあるビーコン）
--   ② wifi_reports_v2  … Wi-Fi のスキャン 5 秒ごと（AP位置設定の AP と、ESP32 AP 表のうち BLE でないもの）
--   （旧 wifi_reports には入れない。2026-11-22 からサーバーは wifi_reports_v2 / ble_reports だけを読む）
--
-- RSSI は scripts/demo_watch.py と同じ式: 1m での強さ − 10·n·log10(距離) ＋ ばらつき ±4dB。距離は高さの差 3m 込み。
--   BLE: -59dBm・n=2.2（-95 より弱いものは見えない）、Wi-Fi: -40dBm・n=2.0（-92 より弱いものは見えない）
-- 位置推定は直近 2 分のスキャンを使うので、マップで見るのは実行してから 1〜2 分の間だけ（もう一度実行すれば続く）。
-- 装置 ID を変えるときは、①② の params の 'demo-01' を書き換える。通報中にしたいときは ① ② の report を true に（ウォッチと同じく両方の表に送る）。
-- BLE が 1 行も入らないとき: 下の「確かめる」の SELECT で、fw が ble- で始まり距離の入った行があるか見る。
-- 動き回る人を続けて入れたいときは scripts/demo_watch.py（docs/AI_WORKFLOW.md §5）。

-- ① BLE のスキャン
with params as (
  select 'demo-01'::text as device_id,
         coalesce(
           null::float8,   -- ← 立つ位置 [m] を決めたいときは null を数字に（例 130.0）
           (select min(distance_m)::float8 + 5 from public.ap_nodes
             where enabled is not false and distance_m is not null and coalesce(fw, '') like 'ble-%'),
           130.0) as x
),
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
insert into public.ble_reports (device_id, scanned_at, created_at, mac01, rssi01, mac02, rssi02, mac03, rssi03, report)
select (select device_id from params), t, t,
       max(mac) filter (where rn = 1), max(rssi) filter (where rn = 1),
       max(mac) filter (where rn = 2), max(rssi) filter (where rn = 2),
       max(mac) filter (where rn = 3), max(rssi) filter (where rn = 3),
       false   -- 通報（② と同じ値に。true にすると demo-01 がマップで赤く光る）
from ranked where rn <= 3
group by t;

-- ② Wi-Fi のスキャン
with params as (
  select 'demo-01'::text as device_id,
         coalesce(
           null::float8,   -- ← 立つ位置 [m] を決めたいときは null を数字に（例 130.0）
           (select min(distance_m)::float8 + 5 from public.ap_nodes
             where enabled is not false and distance_m is not null and coalesce(fw, '') like 'ble-%'),
           130.0) as x
),
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
insert into public.wifi_reports_v2 (device_id, scanned_at, created_at, mac01, rssi01, mac02, rssi02, mac03, rssi03, report)
select (select device_id from params), t, t,
       max(mac) filter (where rn = 1), max(rssi) filter (where rn = 1),
       max(mac) filter (where rn = 2), max(rssi) filter (where rn = 2),
       max(mac) filter (where rn = 3), max(rssi) filter (where rn = 3),
       false   -- 通報（true にすると demo-01 がマップで赤く光る）
from ranked where rn <= 3
group by t;

-- BLE ビーコンとして使える行（fw が ble- で始まり、距離があり、使う）。0 行なら BLE のダミーは入らない
select upper(mac) as mac, label, fw, distance_m, enabled from public.ap_nodes
where coalesce(fw, '') like 'ble-%' order by distance_m nulls last;

-- 入ったか確かめる
select 'ble_reports' as 表, count(*) as 行数 from public.ble_reports where device_id like 'demo-%'
union all
select 'wifi_reports_v2', count(*) from public.wifi_reports_v2 where device_id like 'demo-%';


-- ===== 消すとき（デモが終わったら、この下だけを選んで実行） =====
-- delete from public.ble_reports          where device_id like 'demo-%';
-- delete from public.wifi_reports_v2      where device_id like 'demo-%';
-- delete from public.wifi_reports         where device_id like 'demo-%';
-- delete from public.device_instructions  where device_id like 'demo-%';
-- delete from public.device_segment_state where device_id like 'demo-%';
-- delete from public.entry_current        where device_id like 'demo-%';
-- delete from public.entry_log            where device_id like 'demo-%';
-- delete from public.position_eval        where device_id like 'demo-%';
