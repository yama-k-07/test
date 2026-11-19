// config.example.h を config.h にコピーして、1台ごとに値を書き換える。
// config.h はパスワードとトークンを含むので Git に入れない（.gitignore 済み）。
#pragma once

// ---- このビーコンの設置情報（1台ごとに変える） ----
#define AP_LABEL        "A050"      // 表示名。BLE の名前は "MAMOTCHI-A050" になる（英数字で 17 文字まで）
#define AP_DISTANCE_M   50.0        // 入口からの距離[m]。初回登録時の初期値（以後は管理画面で変更）

// ---- BLE ビーコン ----
#define BLE_TX_POWER    ESP_PWR_LVL_P3   // +3dBm。ESP_PWR_LVL_N0（0dBm）〜 ESP_PWR_LVL_P9（+9dBm）を目安に。全台で揃える
#define BLE_INTERVAL_MS 100              // 広告の間隔[ms]

// ---- 従来の Wi-Fi softAP（使わないなら 0 のまま） ----
#define ENABLE_WIFI_AP  0
#define AP_CHANNEL      1                    // ENABLE_WIFI_AP 1 のときだけ使う
#define AP_PASSWORD     "change-me-8chars"   // ENABLE_WIFI_AP 1 のときだけ使う（8 文字以上）
#define TX_POWER_DBM    8.5                  // ENABLE_WIFI_AP 1 のときの Wi-Fi 出力[dBm]

// ---- 上り回線とサーバー（無ければ "" のままでビーコンだけ動く） ----
#define UPLINK_SSID      ""                  // 現場の Wi-Fi
#define UPLINK_PASSWORD  ""
#define SERVER_BASE_URL  "https://test-fawn-iota-73.vercel.app"
#define AP_TOKEN         ""                  // Vercel の環境変数 AP_SHARED_TOKEN と同じ値

// 本番では接続先の証明書を検証する。ルート CA の PEM を入れると setInsecure() の代わりに使われる
// #define SERVER_ROOT_CA "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
