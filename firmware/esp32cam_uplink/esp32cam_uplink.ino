// まもっち ESP32 カメラ（外から見られるコマ送りカメラ）
//
// インターネットにつながる Wi-Fi（現場の Wi-Fi・モバイルルーター・スマホのテザリング）に接続し、
// ダッシュボード（https://test-fawn-iota-73.vercel.app/）で誰かが「映像を見る」を押している間だけ、
// 約 1 秒ごとに JPEG を 1 枚ずつサーバーへ送る。誰も見ていない間は 10 秒ごとの生存通知だけ。
//
//   10 秒ごと   POST /api/camera_poll   {camera_id, label, distance_m, fw, rssi} → {"send": true/false, ...}
//   send の間   POST /api/camera_frame?camera_id=...（本文は JPEG そのもの）     → {"send": true/false, ...}
//
// ENABLE_LOCAL_VIEW を 1 にすると、今までの CameraWebServer と同じく自分の Wi-Fi も立て、
// 近くでは http://192.168.4.1 でなめらかな映像も見られる（クラウドへの送信と同時に動く）。
//
// 準備:
//   1. いま動いている CameraWebServer のフォルダから board_config.h・camera_pins.h・partitions.csv を
//      このフォルダにコピーする（カメラの機種・ピン配置・パーティションはそのまま使う）。
//      ENABLE_LOCAL_VIEW を 1 にするなら app_httpd.cpp と camera_index.h もコピーする
//   2. config.example.h を config.h にコピーして書き換える
//   3. Arduino IDE で書き込む（ボード設定は README.md）
// 詳しくは同じフォルダの README.md。

#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "board_config.h"   // CameraWebServer からコピー（CAMERA_MODEL_* の選択と camera_pins.h）
#include "config.h"

#ifndef ENABLE_LOCAL_VIEW
#define ENABLE_LOCAL_VIEW 0
#endif
#if ENABLE_LOCAL_VIEW
void startCameraServer();   // app_httpd.cpp
void setupLedFlash();       // app_httpd.cpp
#endif

static const char *FW_VERSION = "1.1.0";
static const uint32_t WIFI_RETRY_MS = 10 * 1000;

static WiFiClientSecure tls;
static uint32_t pollIntervalMs = 10 * 1000;   // サーバーの返事 poll_sec で上書き
static uint32_t frameIntervalMs = 1000;       // サーバーの返事 interval_ms で上書き
static bool sending = false;                  // サーバーが「送って」と言っている間 true
static uint32_t lastPollMs = 0;
static uint32_t lastFrameMs = 0;
static uint32_t lastWifiTryMs = 0;

static bool initCamera() {
  // 設定は CameraWebServer の setup() と同じ。違いは画像の大きさと画質（回線を節約するため）
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAME_SIZE;            // config.h（既定 VGA 640x480）
  config.jpeg_quality = JPEG_QUALITY;        // config.h（数字が小さいほど高画質・大容量）
  config.fb_count = 1;
  config.jpeg_buffer_size = 0;
  if (psramFound()) {
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;   // 古いコマではなく、いちばん新しいコマを取る
  } else {
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  }

#if defined(CAMERA_MODEL_ESP_EYE)
  pinMode(13, INPUT_PULLUP);
  pinMode(14, INPUT_PULLUP);
#endif

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] init failed 0x%x\n", err);
    return false;
  }

  // 向きと色の補正（CameraWebServer の setup() と同じ）
  sensor_t *s = esp_camera_sensor_get();
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);
    s->set_brightness(s, 1);
    s->set_saturation(s, -2);
  }
#if defined(CAMERA_MODEL_M5STACK_WIDE) || defined(CAMERA_MODEL_M5STACK_ESP32CAM)
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);
#endif
#if defined(CAMERA_MODEL_ESP32S3_EYE)
  s->set_vflip(s, 1);   // ESP32-S3-EYE はそのままだと上下逆さまに写る
#endif

  Serial.printf("[CAM] ready (PSRAM %s)\n", psramFound() ? "yes" : "no");
  return true;
}

static void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (lastWifiTryMs != 0 && millis() - lastWifiTryMs < WIFI_RETRY_MS) return;
  lastWifiTryMs = millis();
  Serial.printf("[WIFI] connecting to %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// サーバーの返事 {"interval_ms":1000,"poll_sec":10,"send":true} を読む（JSON ライブラリを使わない簡易版）
static void readInstruction(const String &body) {
  String b = body;
  b.replace(" ", "");
  sending = b.indexOf("\"send\":true") >= 0;
  int i = b.indexOf("\"poll_sec\":");
  if (i >= 0) {
    long sec = b.substring(i + 11).toInt();
    pollIntervalMs = (uint32_t)(sec < 3 ? 3 : sec) * 1000UL;
  }
  i = b.indexOf("\"interval_ms\":");
  if (i >= 0) {
    long ms = b.substring(i + 14).toInt();
    frameIntervalMs = (uint32_t)(ms < 200 ? 200 : ms);
  }
}

static bool beginRequest(HTTPClient &http, const String &path) {
  if (!http.begin(tls, String(SERVER_BASE_URL) + path)) {
    Serial.println("[HTTP] begin failed");
    return false;
  }
  http.setReuse(true);              // 同じ接続を使い回して TLS の手間を減らす
  http.setConnectTimeout(8000);
  http.setTimeout(15000);
  http.addHeader("X-AP-Token", AP_TOKEN);
  return true;
}

static void sendPoll() {
  HTTPClient http;
  if (!beginRequest(http, "/api/camera_poll")) return;
  http.addHeader("Content-Type", "application/json");
  char body[256];
  snprintf(body, sizeof(body),
           "{\"camera_id\":\"%s\",\"label\":\"%s\",\"distance_m\":%.1f,\"fw\":\"%s\",\"rssi\":%ld}",
           CAMERA_ID, CAMERA_LABEL, (double)CAMERA_DISTANCE_M, FW_VERSION, (long)WiFi.RSSI());
  int code = http.POST((uint8_t *)body, strlen(body));
  String res = code > 0 ? http.getString() : "";
  http.end();
  Serial.printf("[POLL] %d %s\n", code, res.c_str());
  if (code == 200) readInstruction(res);
  else sending = false;
}

static void sendFrame() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] capture failed");
    return;
  }
  HTTPClient http;
  if (!beginRequest(http, String("/api/camera_frame?camera_id=") + CAMERA_ID)) {
    esp_camera_fb_return(fb);
    return;
  }
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Frame-Width", String(fb->width));
  http.addHeader("X-Frame-Height", String(fb->height));
  int code = http.POST(fb->buf, fb->len);
  size_t len = fb->len;
  esp_camera_fb_return(fb);
  String res = code > 0 ? http.getString() : "";
  http.end();
  Serial.printf("[FRAME] %u bytes -> %d\n", (unsigned)len, code);
  if (code == 200) readInstruction(res);
  else sending = false;   // 失敗したら次の poll まで待つ
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\n=== MAMOTCHI ESP32 camera fw %s (%s) ===\n", FW_VERSION, CAMERA_ID);

  if (!initCamera()) {
    Serial.println("[CAM] カメラが使えません。board_config.h の機種と配線を確認してください");
  }

#if defined(SERVER_ROOT_CA)
  tls.setCACert(SERVER_ROOT_CA);
#else
  tls.setInsecure();   // 証明書を検証しない（試験用）。本番は config.h に SERVER_ROOT_CA を入れる
#endif

#if ENABLE_LOCAL_VIEW
  // 近くでは今までどおり http://192.168.4.1 で見られるようにする（自分の Wi-Fi を立てつつ、上り回線にもつなぐ）
  // 上り回線につながると、自分の Wi-Fi のチャンネルは上り回線と同じになる（ESP32 の仕様）
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(LOCAL_AP_SSID, LOCAL_AP_PASSWORD);
  WiFi.setSleep(false);
#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif
  startCameraServer();   // app_httpd.cpp（CameraWebServer からコピー）
  Serial.printf("[LOCAL] SSID=%s  http://%s\n", LOCAL_AP_SSID, WiFi.softAPIP().toString().c_str());
#else
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
#endif
  ensureWifi();
}

void loop() {
  ensureWifi();
  if (WiFi.status() != WL_CONNECTED) {
    sending = false;
    delay(200);
    return;
  }

  uint32_t now = millis();
  if (sending) {
    if (now - lastFrameMs >= frameIntervalMs) {
      lastFrameMs = now;
      sendFrame();
      lastPollMs = now;   // 画像を送っている間は poll 不要（返事で次も送るか分かる）
    }
  } else if (lastPollMs == 0 || now - lastPollMs >= pollIntervalMs) {
    lastPollMs = now;
    sendPoll();
  }
  delay(20);
}
