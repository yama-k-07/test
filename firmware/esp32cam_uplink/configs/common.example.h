// 全カメラ共通の設定。common.example.h を common.h にコピーして書き換える（common.h は Git に入らない）。
// 1台ごとに違う値は configs/<カメラID>.h に書く（camera.example.h を参照）。
// 書き込みは: python scripts/flash_camera.py <カメラID> <ポート>
#pragma once

// ---- 画像 ----
#define FRAME_SIZE   FRAMESIZE_VGA   // 640x480。回線が細いなら FRAMESIZE_QVGA（320x240）
#define JPEG_QUALITY 14              // 10〜20 目安。数字が大きいほど軽い
// JPEG で撮れないカメラ（ESP32-S3-EYE など）は RGB565 で撮って変換する
#define RGB_FRAME_SIZE   FRAMESIZE_QVGA
#define RGB_JPEG_QUALITY 60

// ---- 近くで見る（http://192.168.4.1）。Wi-Fi 名はカメラごとのファイルに書く ----
#define ENABLE_LOCAL_VIEW  1
#define LOCAL_AP_PASSWORD  "ここに 8 文字以上のパスワード"

// ---- 位置推定用の BLE ビーコン ----
#define ENABLE_AP_BEACON  1
#define BLE_TX_POWER      ESP_PWR_LVL_P3   // 全ビーコンで揃える

// ---- インターネットにつながる Wi-Fi（2.4GHz。テザリングでも可） ----
#define WIFI_SSID      "ここに Wi-Fi 名"
#define WIFI_PASSWORD  "ここにパスワード"

// ---- サーバー ----
#define SERVER_BASE_URL "https://test-fawn-iota-73.vercel.app"
#define AP_TOKEN        "ここに AP_SHARED_TOKEN と同じ値"
// #define SERVER_ROOT_CA "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
