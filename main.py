import base64
import io
import json
import logging
import os
import re
from datetime import datetime

import piexif
from flask import Flask, jsonify, request
from PIL import Image

from weather import get_weather

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TROLLEYS_DIR = os.path.join(os.path.dirname(__file__), "Trolleys")


def sanitize_for_filename(text: str) -> str:
    """Strip characters illegal in filenames and collapse whitespace to underscores."""
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', "", text)
    text = re.sub(r"\s+", "_", text)
    return text


def to_exif_datetime(ts: str) -> bytes:
    """Convert 'YYYY-MM-DD HH:MM:SS' to EXIF datetime bytes 'YYYY:MM:DD HH:MM:SS'."""
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y:%m:%d %H:%M:%S").encode("ascii")
    except ValueError:
        return ts.encode("ascii")


# ---------------------------------------------------------------------------
# GET /api/status
# ---------------------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Expected JSON body"}), 400

    required_fields = ["timestamp", "location", "timing_label", "image_format", "image_base64"]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    timestamp: str    = data["timestamp"]
    location: str     = data["location"]
    timing_label: str = data["timing_label"]
    image_format: str = data["image_format"]
    image_base64: str = data["image_base64"]

    # --- Decode image ---------------------------------------------------------
    try:
        image_bytes = base64.b64decode(image_base64)
    except Exception:
        return jsonify({"error": "Invalid base64 data in image_base64"}), 400

    # --- Build filenames ------------------------------------------------------
    ts_safe    = sanitize_for_filename(timestamp)
    loc_safe   = sanitize_for_filename(location)
    label_safe = sanitize_for_filename(timing_label)
    base_name  = f"{ts_safe}_{loc_safe}_{label_safe}"

    os.makedirs(TROLLEYS_DIR, exist_ok=True)
    img_filepath  = os.path.join(TROLLEYS_DIR, base_name + ".jpg")
    json_filepath = os.path.join(TROLLEYS_DIR, base_name + ".json")

    # --- Save image with EXIF metadata ----------------------------------------
    try:
        img = Image.open(io.BytesIO(image_bytes))

        exif_ts = to_exif_datetime(timestamp)
        user_comment = (
            b"ASCII\x00\x00\x00"
            + f"location={location}; timing={timing_label}".encode("ascii", errors="replace")
        )

        exif_dict = {
            "0th": {
                piexif.ImageIFD.ImageDescription: location.encode("utf-8"),
                piexif.ImageIFD.DateTime:         exif_ts,
            },
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal:  exif_ts,
                piexif.ExifIFD.DateTimeDigitized: exif_ts,
                piexif.ExifIFD.UserComment:       user_comment,
            },
            "GPS": {},
            "1st": {},
        }

        img.save(img_filepath, format="JPEG", exif=piexif.dump(exif_dict))
        log.info("Saved image: %s", base_name + ".jpg")

    except Exception as exc:
        return jsonify({"error": f"Failed to process image: {exc}"}), 500

    # --- Build JSON record ----------------------------------------------------
    record = {
        "timestamp":    timestamp,
        "location":     location,
        "timing_label": timing_label,
        "image_format": image_format,
        "image_file":   base_name + ".jpg",
    }

    # --- Inject weather data --------------------------------------------------
    try:
        weather = get_weather(location, timestamp)
        record["weather"] = weather
        log.info(
            "Weather for '%s' @ %s: %s (cached=%s)",
            location, timestamp, weather["condition"], weather["cached"],
        )
    except Exception as exc:
        log.error("Weather fetch failed for '%s': %s", location, exc)
        record["weather_error"] = str(exc)

    # --- Save JSON sidecar ----------------------------------------------------
    try:
        with open(json_filepath, "w") as f:
            json.dump(record, f, indent=2)
        log.info("Saved record:  %s", base_name + ".json")
    except Exception as exc:
        log.error("Failed to save JSON record: %s", exc)

    return "", 200


# ---------------------------------------------------------------------------
# POST /api/detections  (stub — not yet implemented)
# ---------------------------------------------------------------------------
@app.route("/api/detections", methods=["POST"])
def api_detections():
    return jsonify({"status": "stub", "message": "Not yet implemented"}), 200


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
