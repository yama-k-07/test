// 1台ごとの設定。camera.example.h を「<カメラID>.h」（例 cam-03.h）にコピーして書き換える（Git に入らない）。
// 共通の値は common.h に書く。書き込みは: python scripts/flash_camera.py cam-03 COM9
#pragma once

#define CAMERA_ID         "cam-03"   // ファイル名と同じにする。英数字・_・- で 17 文字まで（BLE 名 MAMOTCHI-<ID> が 26 文字に収まる）
#define CAMERA_LABEL      "カメラ3"   // 画面に出る名前（初回登録時の初期値。以後は画面で変更）
#define CAMERA_DISTANCE_M 0.0        // 入口からの距離[m]（初回登録時の初期値。以後は画面で変更）
#define LOCAL_AP_SSID     "ssss3"    // 近くで見る Wi-Fi の名前。カメラごとに変える

#include "common.h"
