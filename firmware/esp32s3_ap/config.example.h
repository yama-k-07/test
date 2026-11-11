// config.example.h を config.h にコピーして、1台ごとに値を書き換える。
// config.h はパスワードとトークンを含むので Git に入れない（.gitignore 済み）。
#pragma once

// ---- この AP の設置情報（1台ごとに変える） ----
#define AP_LABEL        "A050"      // 表示名。SSID は "MAMOTCHI-A050" になる
#define AP_DISTANCE_M   50.0        // 入口からの距離[m]。初回登録時の初期値（以後は管理画面で変更）
#define AP_CHANNEL      1           // 隣り合う AP で 1 / 6 / 11 を順に使うと混信しにくい（上り回線ありの場合は無視される）

// ---- softAP ----
#define AP_PASSWORD     "change-me-8chars"   // 8 文字以上。ウォッチは接続しないので共通で構わない
#define TX_POWER_DBM    8.5                  // 送信出力[dBm]。-1〜21。トンネルでは低めから試す

// ---- 上り回線とサーバー（無ければ "" のままで AP だけ動く） ----
#define UPLINK_SSID      ""                  // 現場の Wi-Fi
#define UPLINK_PASSWORD  ""
#define SERVER_BASE_URL  "https://test-fawn-iota-73.vercel.app"
#define AP_TOKEN         ""                  // Vercel の環境変数 AP_SHARED_TOKEN と同じ値

// 本番では接続先の証明書を検証する。ルート CA の PEM を入れると setInsecure() の代わりに使われる
// #define SERVER_ROOT_CA "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
