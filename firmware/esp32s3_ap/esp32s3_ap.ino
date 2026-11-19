// まもっち ESP32-S3 ビーコン（旧 ESP32-S3 AP）
// トンネル内に並べて「位置の目印」にする。既定は BLE ビーコン。ウォッチは接続せず、スキャンして
// 電波の強い順に上位のアドレスと RSSI をサーバーへ送る（ble_reports）。サーバーはそのアドレスの
// 設置距離（管理画面の「ESP32 AP」で設定）から作業者の位置を推定する。
//
// 動作:
//   1. BLE の広告を出す（名前は "MAMOTCHI-<LABEL>"。ウォッチはこの接頭辞で関係ない機器を除く）
//      ENABLE_WIFI_AP 1 にすると、従来どおり Wi-Fi の softAP も立てる（位置の目印には BLE を使う）
//   2. 上り回線（現場の Wi-Fi）があれば接続し、30 秒ごとに /api/ap_heartbeat へ稼働情報を送る
//      → サーバーの ap_nodes に BLE アドレスで自動登録され、ダッシュボードで稼働中／停止が分かる
//   3. 上り回線が無くてもビーコンとしては動く（その場合はシリアルに出るアドレスを管理画面に手で登録する）
//
// ウォッチ側の決まりは docs/WATCH_SCAN_REPORTS.md。
// 開発環境: Arduino IDE / arduino-cli + Arduino-ESP32 コア（ボード: ESP32S3 Dev Module などお使いの S3 ボード）
// 1台ごとに config.h の AP_LABEL / AP_DISTANCE_M を変えて書き込む。

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <BLEDevice.h>   // Arduino-ESP32 の BLE ライブラリ（ESP32-S3 は NimBLE）
#include "config.h"

#ifndef ENABLE_WIFI_AP
#define ENABLE_WIFI_AP 0                 // 1 で従来の Wi-Fi softAP も立てる
#endif
#ifndef BLE_TX_POWER
#define BLE_TX_POWER ESP_PWR_LVL_P3      // +3dBm。ビーコンどうしで揃える
#endif
#ifndef BLE_INTERVAL_MS
#define BLE_INTERVAL_MS 100              // 広告の間隔[ms]。短いほどウォッチが拾いやすい
#endif
#if ENABLE_WIFI_AP
#ifndef AP_CHANNEL
#define AP_CHANNEL 1
#endif
#ifndef TX_POWER_DBM
#define TX_POWER_DBM 8.5
#endif
#endif

static const char *FW_VERSION = "2.0.0";
static const uint32_t HEARTBEAT_INTERVAL_MS = 30 * 1000;   // サーバーの AP_NODE_ONLINE_SEC(90) の 1/3
static const uint32_t UPLINK_RETRY_MS = 15 * 1000;

static String bleName;
static String bleAddress;
static uint32_t lastHeartbeatMs = 0;
static uint32_t lastUplinkTryMs = 0;
static bool uplinkConfigured = false;

// esp_power_level_t → dBm（ESP32-S3 の esp_bt.h の表。N24=0 が -24dBm、3dBm 刻み、P20=15 が +20dBm）
static int bleDbm(int level) { return level >= 15 ? 20 : -24 + level * 3; }

static void startBleBeacon() {
  bleName = String("MAMOTCHI-") + AP_LABEL;   // 広告に入るのは 26 文字まで
  BLEDevice::init(bleName);
  BLEDevice::setPower(BLE_TX_POWER);
  bleAddress = String(BLEDevice::getAddress().toString().c_str());
  bleAddress.toUpperCase();   // サーバーは大文字で比べる（norm_mac）
  BLEAdvertising *adv = BLEDevice::getAdvertising();
  uint16_t units = (uint16_t)(BLE_INTERVAL_MS / 0.625);   // 単位 0.625ms
  adv->setMinInterval(units);
  adv->setMaxInterval(units);
  BLEDevice::startAdvertising();
  Serial.printf("[BLE] name=%s  address=%s  power=%ddBm  interval=%dms\n",
                bleName.c_str(), bleAddress.c_str(), bleDbm(BLE_TX_POWER), (int)BLE_INTERVAL_MS);
  Serial.println("[BLE] 上り回線が無い場合は、この address を管理画面の AP位置設定に登録してください");
}

#if ENABLE_WIFI_AP
// config.h の TX_POWER_DBM に一番近い（それ以下の）設定値を選ぶ
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

static void startWifiAccessPoint() {
  String ssid = String("MAMOTCHI-") + AP_LABEL;
  // パスワード付き・接続数1。上り回線に接続すると、チャンネルは上り回線に合わせて変わる（ESP32 の仕様）
  bool ok = WiFi.softAP(ssid.c_str(), AP_PASSWORD, AP_CHANNEL, 0 /* ssid_hidden */, 1 /* max_connection */);
  WiFi.setTxPower(txPowerFromDbm(TX_POWER_DBM));
  Serial.printf("[WIFI-AP] %s  SSID=%s  BSSID=%s  ch=%d\n", ok ? "started" : "FAILED",
                ssid.c_str(), WiFi.softAPmacAddress().c_str(), AP_CHANNEL);
}
#endif

static void tryUplink() {
  if (!uplinkConfigured || WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastUplinkTryMs < UPLINK_RETRY_MS && lastUplinkTryMs != 0) return;
  lastUplinkTryMs = millis();
  Serial.printf("[UPLINK] connecting to %s\n", UPLINK_SSID);
  WiFi.begin(UPLINK_SSID, UPLINK_PASSWORD);
}

static void sendHeartbeat() {
  if (!uplinkConfigured || WiFi.status() != WL_CONNECTED) return;

  WiFiClientSecure tls;
#if defined(SERVER_ROOT_CA)
  tls.setCACert(SERVER_ROOT_CA);
#else
  // 証明書を検証しない（試験用）。本番は config.h に SERVER_ROOT_CA を入れる
  tls.setInsecure();
#endif

  HTTPClient http;
  String url = String(SERVER_BASE_URL) + "/api/ap_heartbeat";
  if (!http.begin(tls, url)) {
    Serial.println("[HB] http.begin failed");
    return;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-AP-Token", AP_TOKEN);
  http.setTimeout(8000);

  // mac は BLE アドレス（ウォッチが mac01/mac02 として送る値）。tx_power_dbm は BLE の出力
  char body[384];
  snprintf(body, sizeof(body),
           "{\"mac\":\"%s\",\"label\":\"%s\",\"distance_m\":%.1f,\"fw\":\"ble-%s\","
           "\"uptime_s\":%lu,\"sta_count\":0,\"tx_power_dbm\":%d,\"channel\":%ld,\"uplink_rssi\":%ld}",
           bleAddress.c_str(), AP_LABEL, (double)AP_DISTANCE_M, FW_VERSION,
           (unsigned long)(millis() / 1000), bleDbm(BLE_TX_POWER), (long)WiFi.channel(), (long)WiFi.RSSI());

  int code = http.POST((uint8_t *)body, strlen(body));
  Serial.printf("[HB] POST %s -> %d %s\n", url.c_str(), code, code > 0 ? http.getString().c_str() : "");
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\n=== MAMOTCHI ESP32-S3 beacon fw %s ===\n", FW_VERSION);

  uplinkConfigured = strlen(UPLINK_SSID) > 0 && strlen(SERVER_BASE_URL) > 0 && strlen(AP_TOKEN) > 0;
#if ENABLE_WIFI_AP
  WiFi.mode(uplinkConfigured ? WIFI_AP_STA : WIFI_AP);
  startWifiAccessPoint();
#else
  if (uplinkConfigured) WiFi.mode(WIFI_STA);
#endif
  // Wi-Fi と BLE を同時に使うときは Wi-Fi の省電力（modem sleep）を切れない（ESP32 の共存の決まり）
  if (uplinkConfigured || ENABLE_WIFI_AP) WiFi.setSleep(true);

  startBleBeacon();
  tryUplink();
}

void loop() {
  tryUplink();
  bool due = lastHeartbeatMs == 0 || millis() - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS;
  if (uplinkConfigured && WiFi.status() == WL_CONNECTED && due) {
    lastHeartbeatMs = millis();
    sendHeartbeat();
  }
  delay(200);
}
