// config.example.h を config.h にコピーして書き換える。
// config.h は Wi-Fi のパスワードとトークンを含むので Git に入れない（.gitignore 済み）。
#pragma once

// ---- このカメラ ----
#define CAMERA_ID         "cam-entrance"   // 英数字・_・- で 32 文字まで。カメラごとに変える
#define CAMERA_LABEL      "入口カメラ"      // 画面に出る名前（初回登録時の初期値。以後は画面で変更）
#define CAMERA_DISTANCE_M 0.0               // 入口からの距離[m]（初回登録時の初期値）

// ---- 画像 ----
// クラウドに送るため JPEG で撮る（CameraWebServer で使っていた RGB565・240x240 は顔検出用の設定）
#define FRAME_SIZE   FRAMESIZE_VGA   // 640x480。回線が細いなら FRAMESIZE_QVGA（320x240）
#define JPEG_QUALITY 14              // 10〜20 目安。数字が大きいほど軽い（1 枚 20〜50KB 程度）

// ---- 近くで見る（今までの http://192.168.4.1）----
// 1 にすると自分の Wi-Fi も立てて、CameraWebServer の画面（なめらかな映像）も同時に使える。
// そのときは CameraWebServer の app_httpd.cpp と camera_index.h もこのフォルダにコピーする。
#define ENABLE_LOCAL_VIEW  1
#define LOCAL_AP_SSID      "ここに自分の Wi-Fi 名"
#define LOCAL_AP_PASSWORD  "ここに 8 文字以上のパスワード"

// ---- インターネットにつながる Wi-Fi（2.4GHz の WPA2-Personal。テザリングでも可） ----
#define WIFI_SSID      "ここに Wi-Fi 名"
#define WIFI_PASSWORD  "ここにパスワード"

// ---- サーバー ----
#define SERVER_BASE_URL "https://test-fawn-iota-73.vercel.app"
#define AP_TOKEN        "ここに AP_SHARED_TOKEN と同じ値"   // ESP32 AP と共通のトークン

// 本番では接続先の証明書を検証する。ルート CA の PEM を入れると setInsecure() の代わりに使われる
// #define SERVER_ROOT_CA "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
