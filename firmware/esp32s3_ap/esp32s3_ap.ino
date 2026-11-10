// まもっち ESP32-S3 AP
// トンネル内に並べて「位置の目印」にする Wi-Fi AP。ウォッチはこの AP に接続せず、スキャンして
// 電波の強い順に2つの BSSID（mac01 / mac02）をサーバーへ送る。サーバーはその BSSID の
// 設置距離（管理画面の「ESP32 AP」で設定）から作業者の位置を推定する。
//
// 動作:
//   1. softAP を立てる（SSID は "MAMOTCHI-<LABEL>"。ウォッチ側はこの接頭辞で関係ない AP を除外できる）
//   2. 上り回線（現場の Wi-Fi）があれば接続し、30 秒ごとに /api/ap_heartbeat へ稼働情報を送る
//      → サーバーの ap_nodes に自動登録され、ダッシュボードで稼働中／停止が分かる
//   3. 上り回線が無くても AP としては動く（その場合はシリアルに出る BSSID を管理画面に手で登録する）
//
// 開発環境: Arduino IDE / arduino-cli + Arduino-ESP32 コア（ボード: ESP32S3 Dev Module などお使いの S3 ボード）
// 1台ごとに config.h の AP_LABEL / AP_DISTANCE_M / AP_CHANNEL を変えて書き込む。

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "config.h"

static const char *FW_VERSION = "1.0.0";
static const uint32_t HEARTBEAT_INTERVAL_MS = 30 * 1000;   // サーバーの AP_NODE_ONLINE_SEC(90) の 1/3
static const uint32_t UPLINK_RETRY_MS = 15 * 1000;

static String apSsid;
static String apBssid;
static uint32_t lastHeartbeatMs = 0;
static uint32_t lastUplinkTryMs = 0;
static bool uplinkConfigured = false;

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

static void startAccessPoint() {
  apSsid = String("MAMOTCHI-") + AP_LABEL;
  // パスワード付き・接続数1: ウォッチはスキャンするだけなので接続させない（BSSID はスキャンで見える）
  // 注意: 上り回線に接続すると、softAP のチャンネルは上り回線のチャンネルに合わせて変わる（ESP32 の仕様）
  bool ok = WiFi.softAP(apSsid.c_str(), AP_PASSWORD, AP_CHANNEL, 0 /* ssid_hidden */, 1 /* max_connection */);
  apBssid = WiFi.softAPmacAddress();
  Serial.printf("[AP] %s  SSID=%s  BSSID=%s  ch=%d\n", ok ? "started" : "FAILED",
                apSsid.c_str(), apBssid.c_str(), AP_CHANNEL);
  Serial.println("[AP] 上り回線が無い場合は、この BSSID を管理画面の AP位置設定に登録してください");
}

static void applyTxPower() {
  // 出力を下げると遠くの AP が「強い順の上位」に入りにくくなる。トンネルは電波が遠くまで届く（導波管効果）ため、
  // 隣の AP が 1〜2 台先まで届く程度に抑えるのが目安。現地で受信強度を見て config.h で調整する。
  bool ok = WiFi.setTxPower(txPowerFromDbm(TX_POWER_DBM));
  Serial.printf("[AP] tx power request %.1f dBm -> %s (current=%d x0.25dBm)\n",
                (double)TX_POWER_DBM, ok ? "ok" : "FAILED", (int)WiFi.getTxPower());
}

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

  char body[384];
  snprintf(body, sizeof(body),
           "{\"mac\":\"%s\",\"label\":\"%s\",\"distance_m\":%.1f,\"fw\":\"%s\","
           "\"uptime_s\":%lu,\"sta_count\":%u,\"tx_power_dbm\":%.1f,\"channel\":%ld,\"uplink_rssi\":%ld}",
           apBssid.c_str(), AP_LABEL, (double)AP_DISTANCE_M, FW_VERSION,
           (unsigned long)(millis() / 1000), (unsigned)WiFi.softAPgetStationNum(),
           (double)TX_POWER_DBM, (long)WiFi.channel(), (long)WiFi.RSSI());

  int code = http.POST((uint8_t *)body, strlen(body));
  Serial.printf("[HB] POST %s -> %d %s\n", url.c_str(), code, code > 0 ? http.getString().c_str() : "");
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\n=== MAMOTCHI ESP32-S3 AP fw %s ===\n", FW_VERSION);

  uplinkConfigured = strlen(UPLINK_SSID) > 0 && strlen(SERVER_BASE_URL) > 0 && strlen(AP_TOKEN) > 0;
  WiFi.mode(uplinkConfigured ? WIFI_AP_STA : WIFI_AP);
  WiFi.setSleep(false);   // ビーコンを安定して出すため省電力を切る

  startAccessPoint();
  applyTxPower();
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
