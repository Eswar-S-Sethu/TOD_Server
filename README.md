# TOD Server

A lightweight Flask server that receives camera captures from remote units, decodes the images, stores them with embedded EXIF metadata, and enriches each capture with local weather data from Open-Meteo.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Weather Integration](#weather-integration)
- [Local Development](#local-development)
- [NUC Deployment](#nuc-deployment)
  - [1. Prepare the NUC](#1-prepare-the-nuc)
  - [2. Copy the Project](#2-copy-the-project)
  - [3. Run the Install Script](#3-run-the-install-script)
- [Cloudflare Tunnel Setup](#cloudflare-tunnel-setup)
  - [1. Install cloudflared](#1-install-cloudflared)
  - [2. Authenticate](#2-authenticate)
  - [3. Create the Tunnel](#3-create-the-tunnel)
  - [4. Write the Config File](#4-write-the-config-file)
  - [5. Route DNS](#5-route-dns)
  - [6. Install the cloudflared Service](#6-install-the-cloudflared-service)
  - [7. Verify](#7-verify)
- [Managing the Services](#managing-the-services)
- [API Reference](#api-reference)
- [Image Storage](#image-storage)

---

## How It Works

Camera units send JPEG images (base64-encoded) to `POST /api/upload` along with a timestamp, location label, and timing label. The server:

1. Decodes the base64 image.
2. Embeds the timestamp and location into the image's EXIF metadata.
3. Saves the image to the `Trolleys/` directory with a descriptive filename.
4. Fetches weather data for the capture timestamp from Open-Meteo (or reuses a cached result if a previous payload from the same location arrived within 30 minutes).
5. Saves a `.json` sidecar file alongside the image containing the full payload metadata and the weather block.

Camera units poll `GET /api/status` at the start of each cycle to check for a kill signal.

---

## Weather Integration

Weather data is fetched from [Open-Meteo](https://open-meteo.com/) — no API key or account required. Coordinates are resolved automatically from the `location` field in the payload using the Open-Meteo Geocoding API, so no configuration is needed. Place names like `"Chadstone"` or `"Mount Waverley"` are geocoded on first use and the result is cached for the lifetime of the process.

### How the cache works

Two caches run in memory:

**Geocoding cache** — coordinates for a place name never change, so they are cached permanently (until the server restarts). The first payload from a new location triggers one geocoding call; all subsequent payloads reuse it.

**Weather cache** — each location has its own entry keyed to the timestamp that triggered the last fetch. When a new payload arrives:

1. The server checks whether the incoming timestamp is **within 30 minutes** of the cached reference timestamp for that location.
2. If yes — the cached weather block is reused, no API call is made.
3. If no — fresh hourly weather is fetched and the cache is updated.

This means a burst of uploads from the same camera within half an hour makes exactly one weather API call.

### JSON sidecar format

For every upload a `.json` file is saved alongside the image in `Trolleys/`:

```json
{
  "timestamp":    "2024-01-15 09:30:00",
  "location":     "Front Door Entrance",
  "timing_label": "start_of_minute",
  "image_format": "jpg",
  "image_file":   "2024-01-15_09-30-00_Front_Door_Entrance_start_of_minute.jpg",
  "weather": {
    "temperature_c":        12.3,
    "relative_humidity_pct": 65,
    "precipitation_mm":     0.0,
    "wind_speed_kmh":       15.2,
    "weather_code":         1,
    "condition":            "Mainly clear",
    "reference_hour":       "2024-01-15T09:00",
    "source":               "Open-Meteo",
    "cached":               false
  }
}
```

`cached: true` means the weather block was reused from a previous fetch within the 30-minute window. `cached: false` means a fresh API call was made.

---

## Project Structure

```
TOD_Server/
├── main.py                  # Flask application
├── weather.py               # Geocoding + Open-Meteo fetching + 30-min cache
├── Trolleys/                # Created automatically — images and JSON sidecars land here
├── deploy/
│   ├── tod-server.service   # systemd unit for the Flask app
│   └── install.sh           # One-shot install script for the NUC
├── ENDPOINTS.md             # Full API contract reference
└── README.md
```

---

## Local Development

**Requirements:** Python 3.10+, pip

```bash
# Clone the repo and enter it
git clone <repo-url>
cd TOD_Server

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install flask pillow piexif

# Run the server
python main.py
```

The server starts on `http://0.0.0.0:5000`.

Saved images appear in `Trolleys/` relative to `main.py`.

---

## NUC Deployment

The target machine is an Intel NUC running Ubuntu or Debian. The server runs as a systemd service so it starts on boot and restarts on failure.

### 1. Prepare the NUC

SSH into the NUC and ensure Python 3 and rsync are available:

```bash
sudo apt update && sudo apt install -y python3 python3-venv rsync
```

### 2. Copy the Project

From your dev machine, push the project to the NUC:

```bash
rsync -av --exclude='.git' --exclude='Trolleys' --exclude='.venv' \
  /path/to/TOD_Server/ user@nuc-ip:/opt/tod-server/
```

Or clone directly on the NUC if the repo is remote:

```bash
git clone <repo-url> /opt/tod-server
```

### 3. Run the Install Script

On the NUC, run the install script as root. Pass your Linux username as the first argument:

```bash
sudo bash /opt/tod-server/deploy/install.sh your-username
```

The script will:

- Create a Python venv at `/opt/tod-server/.venv` and install dependencies.
- Patch your username into `tod-server.service` and install it to `/etc/systemd/system/`.
- Enable and start the `tod-server` service.
- Install and start the `cloudflared` service (requires cloudflare setup below to be done first).

> **Note:** Complete the [Cloudflare Tunnel Setup](#cloudflare-tunnel-setup) section before running the install script, as it calls `cloudflared service install` at the end.

---

## Cloudflare Tunnel Setup

This exposes the local server to the internet with a stable, permanent URL — no open firewall ports required. You need a Cloudflare account with a domain already added to it.

### 1. Install cloudflared

On the NUC:

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
  -o cloudflared.deb
sudo dpkg -i cloudflared.deb
cloudflared --version
```

### 2. Authenticate

```bash
cloudflared tunnel login
```

This prints a URL. Open it in a browser, log in to your Cloudflare account, and select the domain you want to use. A certificate is saved to `~/.cloudflared/cert.pem`.

### 3. Create the Tunnel

```bash
cloudflared tunnel create tod-server
```

The output includes a **Tunnel ID** (a UUID). Copy it — you need it in the next step. A credentials JSON file is saved to `~/.cloudflared/<TUNNEL_ID>.json`.

### 4. Write the Config File

```bash
nano ~/.cloudflared/config.yml
```

Paste the following, replacing the placeholders:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/<your-username>/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: api.yourdomain.com
    service: http://localhost:5000
  - service: http_status:404
```

- `<TUNNEL_ID>` — the UUID from step 3.
- `<your-username>` — your Linux username on the NUC.
- `api.yourdomain.com` — the subdomain you want the server accessible at. It must be on a domain already managed in Cloudflare.

### 5. Route DNS

This creates a CNAME record in Cloudflare automatically:

```bash
cloudflared tunnel route dns tod-server api.yourdomain.com
```

Verify it appears in your Cloudflare dashboard under DNS.

### 6. Install the cloudflared Service

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

> If you ran the install script from the deployment section, this is already done.

### 7. Verify

```bash
# Check both services are running
systemctl is-active tod-server
systemctl is-active cloudflared

# Hit the status endpoint through the tunnel
curl https://api.yourdomain.com/api/status
# Expected: {"status": "ok"}
```

---

## Managing the Services

| Task | Command |
|---|---|
| View Flask logs (live) | `journalctl -u tod-server -f` |
| View tunnel logs (live) | `journalctl -u cloudflared -f` |
| Restart Flask | `sudo systemctl restart tod-server` |
| Restart tunnel | `sudo systemctl restart cloudflared` |
| Stop Flask | `sudo systemctl stop tod-server` |
| Stop tunnel | `sudo systemctl stop cloudflared` |
| Check Flask status | `systemctl status tod-server` |
| Check tunnel status | `systemctl status cloudflared` |

**Updating the server code:**

```bash
# Pull latest code on the NUC
cd /opt/tod-server && git pull

# Restart the service to pick up changes
sudo systemctl restart tod-server
```

---

## API Reference

See [ENDPOINTS.md](ENDPOINTS.md) for the full contract. Summary:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | Poll for kill signal. Returns `{"status": "ok"}` to continue. |
| `POST` | `/api/upload` | Receive and store a camera capture. |
| `POST` | `/api/detections` | Stub — not yet implemented. |

### POST /api/upload — Request Body

```json
{
    "timestamp":    "2024-01-15 09:30:00",
    "location":     "Front Door Entrance",
    "timing_label": "start_of_minute",
    "image_format": "jpg",
    "image_base64": "<base64-encoded JPEG>"
}
```

Returns HTTP `200` on success. Any other response causes the camera unit to save a local fallback and retry.

---

## Image Storage

Images are saved to the `Trolleys/` directory (created automatically at `/opt/tod-server/Trolleys/` on the NUC).

**Filename format:**

```
<timestamp>_<location>_<timing_label>.jpg
```

Example: `2024-01-15_09-30-00_Front_Door_Entrance_start_of_minute.jpg`

**Embedded EXIF metadata:**

| EXIF Tag | Value |
|---|---|
| `ImageDescription` | Location label from the payload |
| `DateTime` | Capture timestamp |
| `DateTimeOriginal` | Capture timestamp |
| `DateTimeDigitized` | Capture timestamp |
| `UserComment` | `location=<location>; timing=<timing_label>` |
