// まもっち ESP32 カメラ（外から見られるコマ送りカメラ）
//
// インターネットにつながる Wi-Fi（現場の Wi-Fi・モバイルルーター・スマホのテザリング）に接続し、
// ダッシュボード（https://test-fawn-iota-73.vercel.app/）で誰かが「映像を見る」を押している間だけ、
// 約 1 秒ごとに JPEG を 1 枚ずつサーバーへ送る。誰も見ていない間は 10 秒ごとの生存通知だけ。
//
//   10 秒ごと   POST /api/camera_poll   {camera_id, label, distance_m, fw, rssi, ap_mac} → {"send": true/false, ...}
//   send の間   POST /api/camera_frame?camera_id=...（本文は JPEG そのもの）     → {"send": true/false, ...}
//
// ENABLE_LOCAL_VIEW を 1 にすると、今までの CameraWebServer と同じく自分の Wi-Fi も立て、
// 近くでは http://192.168.4.1 でなめらかな映像も見られる（クラウドへの送信と同時に動く）。
//
// ENABLE_AP_BEACON を 1（既定）にすると、位置推定用の AP も兼ねる（firmware/esp32s3_ap と同じ役目）。
// 自分の Wi-Fi（LOCAL_AP_SSID）の BSSID を 30 秒ごとに POST /api/ap_heartbeat で知らせるので、
// ダッシュボードの「ESP32 AP」表に出る。そこで距離を入れると、ウォッチの位置推定に使われる。
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
#include "img_converters.h"   // frame2jpg（JPEG で撮れないカメラ用）
#include "board_config.h"   // CameraWebServer からコピー（CAMERA_MODEL_* の選択と camera_pins.h）
#include "config.h"

#ifndef ENABLE_LOCAL_VIEW
#define ENABLE_LOCAL_VIEW 0
#endif
// 位置推定用の AP を兼ねる（config.h に無ければ兼ねる）
#ifndef ENABLE_AP_BEACON
#define ENABLE_AP_BEACON 1
#endif
#ifndef AP_LABEL
#define AP_LABEL CAMERA_LABEL               // ESP32 AP 表に出る名前（初回登録時の初期値）
#endif
#ifndef AP_DISTANCE_M
#define AP_DISTANCE_M CAMERA_DISTANCE_M     // 入口からの距離[m]（初回登録時の初期値。以後は画面で変更）
#endif
#ifndef AP_TX_POWER_DBM
#define AP_TX_POWER_DBM 8.5                 // esp32s3_ap と同じ既定値。上り回線の電波も同じ出力になる
#endif
#if (ENABLE_LOCAL_VIEW || ENABLE_AP_BEACON) && !defined(LOCAL_AP_SSID)
#error "LOCAL_AP_SSID / LOCAL_AP_PASSWORD を config.h に書いてください（自分の Wi-Fi の名前とパスワード）"
#endif
// JPEG で撮れないカメラ用（config.h に無ければこの値）
#ifndef RGB_FRAME_SIZE
#define RGB_FRAME_SIZE FRAMESIZE_QVGA   // 320x240。RGB565 は 1 コマが大きいので小さめにする
#endif
#ifndef RGB_JPEG_QUALITY
#define RGB_JPEG_QUALITY 60             // frame2jpg の画質（0〜100、大きいほど高画質・大容量）
#endif
#if ENABLE_LOCAL_VIEW
void startCameraServer();   // app_httpd.cpp
void setupLedFlash();       // app_httpd.cpp
#endif

static const char *FW_VERSION = "1.3.0";
static const uint32_t WIFI_RETRY_MS = 10 * 1000;
static const uint32_t HEARTBEAT_INTERVAL_MS = 30 * 1000;   // サーバーの AP_NODE_ONLINE_SEC(90) の 1/3

static WiFiClientSecure tls;
static uint32_t pollIntervalMs = 10 * 1000;   // サーバーの返事 poll_sec で上書き
static uint32_t frameIntervalMs = 1000;       // サーバーの返事 interval_ms で上書き
static bool sending = false;                  // サーバーが「送って」と言っている間 true
static uint32_t lastPollMs = 0;
static uint32_t lastFrameMs = 0;
static uint32_t lastWifiTryMs = 0;
static uint32_t lastHeartbeatMs = 0;
static String apBssid;                        // 自分の Wi-Fi の BSSID（ウォッチが mac01/mac02 として送る値）

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
  if (err == ESP_ERR_NOT_SUPPORTED) {
    // JPEG で撮れない撮像素子（ESP32-S3-EYE の一部など）。RGB565 で撮り、送るときに JPEG に変換する
    Serial.println("[CAM] このカメラは JPEG で撮れないため、RGB565 で撮って変換します");
    config.pixel_format = PIXFORMAT_RGB565;
    config.frame_size = RGB_FRAME_SIZE;       // config.h（既定 QVGA 320x240）
    err = esp_camera_init(&config);
  }
  if (err != ESP_OK) {
    Serial.printf("[CAM] init failed 0x%x\n", err);
    return false;
  }

  // 向きと色の補正（CameraWebServer の setup() と同じ）
  sensor_t *s = esp_camera_sensor_get();
  Serial.printf("[CAM] sensor PID 0x%x, format %s\n", s->id.PID,
                config.pixel_format == PIXFORMAT_JPEG ? "JPEG" : "RGB565 -> JPEG");
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
  // ap_mac: 位置推定用の AP を兼ねるとき、その BSSID（サーバーがカメラの距離を ESP32 AP 表と連動させる）
  char body[320];
  snprintf(body, sizeof(body),
           "{\"camera_id\":\"%s\",\"label\":\"%s\",\"distance_m\":%.1f,\"fw\":\"%s\",\"rssi\":%ld,\"ap_mac\":\"%s\"}",
           CAMERA_ID, CAMERA_LABEL, (double)CAMERA_DISTANCE_M, FW_VERSION, (long)WiFi.RSSI(),
           ENABLE_AP_BEACON ? apBssid.c_str() : "");
  int code = http.POST((uint8_t *)body, strlen(body));
  String res = code > 0 ? http.getString() : "";
  http.end();
  Serial.printf("[POLL] %d %s\n", code, res.c_str());
  if (code == 200) readInstruction(res);
  else sending = false;
}

#if ENABLE_AP_BEACON
// AP_TX_POWER_DBM に一番近い（それ以下の）設定値を選ぶ（esp32s3_ap.ino と同じ）
static wifi_power_t txPowerFromDbm(float dbm) {
  struct { float dbm; wifi_power_t value; } table[] = {
    {21, WIFI_POWER_21dBm}, {20.5, WIFI_POWER_20_5dBm}, {20, WIFI_POWER_20dBm},
    {19.5, WIFI_POWER_19_5dBm}, {19, WIFI_POWER_19dBm}, {18.5, WIFI_POWER_18_5dBm},
    {17, WIFI_POWER_17dBm}, {15, WIFI_POWER_15dBm}, {13, WIFI_POWER_13dBm},
    {11, WIFI_POWER_11dBm}, {8.5, WIFI_POWER_8_5dBm}, {7, WIFI_POWER_7dBm},
    {5, WIFI_POWER_5dBm}, {2, WIFI_POWER_2dBm}, {-1, WIFI_POWER_MINUS_1dBm},
  };
  for (auto &t : table) {
    if (dbm >= t.dbm) return t.value;
  }
  return WIFI_POWER_MINUS_1dBm;
}

static void applyTxPower() {
  bool ok = WiFi.setTxPower(txPowerFromDbm(AP_TX_POWER_DBM));
  Serial.printf("[AP] tx power request %.1f dBm -> %s (current=%d x0.25dBm)\n",
                (double)AP_TX_POWER_DBM, ok ? "ok" : "FAILED", (int)WiFi.getTxPower());
}

// esp32s3_ap.ino の sendHeartbeat と同じ項目（サーバーの ap_heartbeat が受ける形）
static void sendHeartbeat() {
  HTTPClient http;
  if (!beginRequest(http, "/api/ap_heartbeat")) return;
  http.addHeader("Content-Type", "application/json");
  char body[384];
  snprintf(body, sizeof(body),
           "{\"mac\":\"%s\",\"label\":\"%s\",\"distance_m\":%.1f,\"fw\":\"cam-%s\","
           "\"uptime_s\":%lu,\"sta_count\":%u,\"tx_power_dbm\":%.1f,\"channel\":%ld,\"uplink_rssi\":%ld}",
           apBssid.c_str(), AP_LABEL, (double)AP_DISTANCE_M, FW_VERSION,
           (unsigned long)(millis() / 1000), (unsigned)WiFi.softAPgetStationNum(),
           (double)AP_TX_POWER_DBM, (long)WiFi.channel(), (long)WiFi.RSSI());
  int code = http.POST((uint8_t *)body, strlen(body));
  String res = code > 0 ? http.getString() : "";
  http.end();
  Serial.printf("[HB] %d %s\n", code, res.c_str());
}
#endif

static void sendFrame() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] capture failed");
    return;
  }

  // JPEG で撮れないカメラは、ここで JPEG に変換する（app_httpd.cpp の stream_handler と同じ frame2jpg）
  uint8_t *jpg = fb->buf;
  size_t len = fb->len;
  uint8_t *converted = NULL;
  size_t width = fb->width, height = fb->height;
  if (fb->format != PIXFORMAT_JPEG) {
    bool ok = frame2jpg(fb, RGB_JPEG_QUALITY, &converted, &len);
    esp_camera_fb_return(fb);
    fb = NULL;
    if (!ok) {
      Serial.println("[CAM] JPEG 変換に失敗");
      return;
    }
    jpg = converted;
  }

  HTTPClient http;
  int code = -1;
  if (beginRequest(http, String("/api/camera_frame?camera_id=") + CAMERA_ID)) {
    http.addHeader("Content-Type", "image/jpeg");
    http.addHeader("X-Frame-Width", String(width));
    http.addHeader("X-Frame-Height", String(height));
    code = http.POST(jpg, len);
  }
  if (fb) esp_camera_fb_return(fb);
  if (converted) free(converted);
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

#if ENABLE_LOCAL_VIEW || ENABLE_AP_BEACON
  // 自分の Wi-Fi を立てつつ、上り回線にもつなぐ。この Wi-Fi は「近くで見る画面」と「位置推定用の AP」を兼ねる
  // 上り回線につながると、自分の Wi-Fi のチャンネルは上り回線と同じになる（ESP32 の仕様）
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(LOCAL_AP_SSID, LOCAL_AP_PASSWORD);
  WiFi.setSleep(false);   // ビーコンを安定して出すため省電力を切る
  apBssid = WiFi.softAPmacAddress();
#else
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
#endif
#if ENABLE_AP_BEACON
  applyTxPower();
  Serial.printf("[AP] SSID=%s  BSSID=%s（位置推定用。ESP32 AP 表で距離を設定）\n", LOCAL_AP_SSID, apBssid.c_str());
#endif
#if ENABLE_LOCAL_VIEW
#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif
  startCameraServer();   // app_httpd.cpp（CameraWebServer からコピー）
  Serial.printf("[LOCAL] SSID=%s  http://%s\n", LOCAL_AP_SSID, WiFi.softAPIP().toString().c_str());
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
#if ENABLE_AP_BEACON
  if (lastHeartbeatMs == 0 || now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    sendHeartbeat();
  }
#endif
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
