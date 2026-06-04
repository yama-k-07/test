import json
import time
import requests

CONFIG_PATH = "M5test.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def post_alive(server_url, payload):
    url = server_url.rstrip("/") + "/api/alive_check"
    try:
        r = requests.post(url, json=payload, timeout=3)
        print(f"[{payload['device_id']}] {r.status_code} {r.text}")
    except requests.RequestException as e:
        print(f"[{payload['device_id']}] request error: {e}")


def main():
    print("M5 alive_check emulator started")

    while True:
        config = load_config()
        server_url = config["server_url"]
        interval = config.get("interval_sec", 5)

        for dev in config["devices"]:
            payload = {
                "device_id": dev["device_id"],
                "gateway": dev.get("gateway", ""),
                "ssid": dev.get("ssid", ""),
                "username": dev.get("username", ""),
                "report": bool(dev.get("report", False)),
            }

            post_alive(server_url, payload)

        time.sleep(interval)


if __name__ == "__main__":
    main()
