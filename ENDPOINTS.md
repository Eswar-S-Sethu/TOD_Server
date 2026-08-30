# Server Endpoints Reference

Base URL: `https://your-server.com`

---

## GET `/api/status`

Used by the camera unit to poll for a kill signal at the start of each loop cycle and once mid-cycle.

### Request

| Field | Value |
|---|---|
| Method | `GET` |
| Body | None |
| Timeout | 5 seconds |

### Response

The server must return HTTP `200` with a JSON body. Any non-200 response or network failure is treated as "continue running".

**Stop the program:**
```json
{ "kill": true }
```
```json
{ "status": "stop" }
```

**Continue running:**
```json
{ "kill": false }
```
```json
{ "status": "ok" }
```

Either field (`kill` or `status`) is sufficient. If both are present, either condition being true triggers a stop.

---

## POST `/api/upload`

Receives a single camera capture — the image, timestamp, and location metadata.

### Request

| Field | Value |
|---|---|
| Method | `POST` |
| Content-Type | `application/json` |
| Timeout | 10 seconds |

### Request Body

```json
{
    "timestamp":    "2024-01-15 09:30:00",
    "location":     "Front Door Entrance",
    "timing_label": "start_of_minute",
    "image_format": "jpg",
    "image_base64": "<base64-encoded JPEG string>"
}
```

### Field Descriptions

| Field | Type | Description |
|---|---|---|
| `timestamp` | `string` | Local capture time, format `YYYY-MM-DD HH:MM:SS` |
| `location` | `string` | Fixed label identifying the camera unit |
| `timing_label` | `string` | Either `"start_of_minute"` or `"end_of_minute"` |
| `image_format` | `string` | Always `"jpg"` |
| `image_base64` | `string` | Base64-encoded JPEG. Maximum decoded size: 1 MB |

### Response

| Status | Meaning |
|---|---|
| `200` | Payload accepted. The camera unit will not save a local fallback file. |
| Any other / timeout | Treated as failure. The camera unit saves the payload locally and retries on the next cycle. |

The response body is not read by the camera unit — only the status code matters.

---

## POST `/api/detections` *(STUB — not yet implemented)*

Will receive YOLO detection results separately from the image, once the model is trained and integrated. This endpoint and its corresponding client function are stubs; no data is sent yet.

### Request

| Field | Value |
|---|---|
| Method | `POST` |
| Content-Type | `application/json` |
| Timeout | TBD |

### Request Body (planned)

```json
{
    "timestamp":    "2024-01-15 09:30:00",
    "location":     "Front Door Entrance",
    "timing_label": "start_of_minute",
    "detections": [
        {
            "label":      "person",
            "confidence": 0.94,
            "bbox":       [120, 45, 380, 510]
        }
    ]
}
```

### Field Descriptions

| Field | Type | Description |
|---|---|---|
| `timestamp` | `string` | Local capture time, format `YYYY-MM-DD HH:MM:SS` |
| `location` | `string` | Fixed label identifying the camera unit |
| `timing_label` | `string` | Either `"start_of_minute"` or `"end_of_minute"` |
| `detections` | `array` | List of YOLO detection objects |

### Detection Object

| Field | Type | Description |
|---|---|---|
| `label` | `string` | Detected class name (e.g. `"person"`, `"car"`) |
| `confidence` | `float` | Confidence score, range `0.0` – `1.0` |
| `bbox` | `array[int]` | Bounding box as `[x1, y1, x2, y2]` in pixel coordinates relative to the original frame |

### Response

TBD — to be defined when the endpoint is implemented.

---

## Retry Behaviour

When a POST to `/api/upload` fails, the camera unit saves the payload as a local JSON file (`capture_YYYYMMDD_HHMMSS_<label>.json`). At the start of the next loop cycle, all pending local files are replayed against `/api/upload` in chronological order. Successfully uploaded files are deleted; failed ones remain for the following cycle.

Retry behaviour for `/api/detections` is TBD.
