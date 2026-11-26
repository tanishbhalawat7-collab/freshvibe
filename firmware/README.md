# ESP32-CAM firmware notes

Fresh Vibe works with the **stock Arduino `CameraWebServer` example**. No custom firmware is needed.

## Endpoints the bridge uses
| Port | Path | Used for |
|---|---|---|
| 80 | `/capture` | Single JPEG still. Also the health check |
| 81 | `/stream` | MJPEG live view (`multipart/x-mixed-replace`) |
| 80 | `/control?var=…&val=…` | Optional: frame size, flash LED, flip |

`/status` is **not** used, so a 404 there (as on your board) does no harm.

## Recommended Arduino settings
* Board: **AI Thinker ESP32-CAM**
* Partition scheme: **Huge APP (3MB No OTA)**
* PSRAM: **Enabled**
* In `CameraWebServer.ino`: keep `#define CAMERA_MODEL_AI_THINKER` and comment out the other models
* Set your Wi-Fi `ssid` and `password`

## Optional: fixed IP in the sketch
A router DHCP reservation is easiest. If you prefer to fix the IP in code, add this before `WiFi.begin(...)`:
```cpp
IPAddress local_IP(192, 168, 1, 65), gateway(192, 168, 1, 1), subnet(255, 255, 255, 0), dns(192, 168, 1, 1);
WiFi.config(local_IP, gateway, subnet, dns);
```

## Optional: start at a good resolution for reading text
In `setup()`, after `esp_camera_init`:
```cpp
sensor_t *s = esp_camera_sensor_get();
s->set_framesize(s, FRAMESIZE_XGA);   // 1024x768: good balance of detail and speed
s->set_quality(s, 10);                // lower = better JPEG quality
```
You can also change these at runtime from **Connect Camera → Image settings**.

## Flash LED
The AI Thinker board's flash LED is on GPIO 4. Recent CameraWebServer versions expose it as `led_intensity` when `LED_GPIO_NUM` is defined (it is, for `CAMERA_MODEL_AI_THINKER`). Older versions don't, and the app then reports "unsupported" for that control.

## Power
Use a stable 5 V / 2 A supply. Most "random" capture failures (truncated JPEGs, Wi-Fi drops, resets) come from weak USB power.
