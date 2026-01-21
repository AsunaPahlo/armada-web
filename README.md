# <img src="app/static/armada_logo.png" alt="Armada Logo" height="60"> Armada

A real-time submarine and airship fleet monitoring dashboard for FINAL FANTASY XIV. Track all your voyages across multiple accounts and Free Companies from a single interface.

## Features

- **Real-time Monitoring** — See voyage status, return times, and loot across your entire fleet
- **Multi-Account Support** — Connect multiple game clients and view all submarines in one place
- **Multi-FC Support** — Track submarines across different Free Companies
- **Unified Dashboard** — Single pane of glass for all your fleet operations
- **Voyage History** — Track past voyages and analyze returns
- **Alerts & Notifications** — Know when supplies are low, subs are not going, subs are on wrong route

## How It Works

Armada consists of two components:

1. **Server (Web Dashboard)** — A self-hosted web application that displays your fleet data
2. **Dalamud Plugin** — Runs in-game and sends submarine data to the server

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  FFXIV Client   │     │  FFXIV Client   │     │  FFXIV Client   │
│  (Account 1)    │     │  (Account 2)    │     │  (Account 3)    │
│  + Armada Plugin│     │  + Armada Plugin│     │  + Armada Plugin│
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │     Armada Server      │
                    │    (Web Dashboard)     │
                    └────────────────────────┘
```

## Quick Start

### Option 1: Managed Hosting

Don't want to self-host? We offer managed hosting so you can skip the server setup.

**[Contact on Discord](#)** to get started.

### Option 2: Self-Host with Docker Image (Recommended)

1. Create a `docker-compose.yml` file:
   ```yaml
   services:
     armada:
       image: asunapahlo/armada:latest
       container_name: armada
       restart: unless-stopped
       ports:
         - "5000:5000"
       volumes:
         - armada_data:/app/data
       environment:
         - SECRET_KEY=change-this-to-a-random-secret-key  # Required: set a secure key

   volumes:
     armada_data:
   ```

2. Set a secure `SECRET_KEY` (generate one with: `openssl rand -hex 32`)

3. Start the server:
   ```bash
   docker compose up -d
   ```

4. Access the dashboard at `http://localhost:5000`

5. Create an account and generate API keys for your game clients

### Option 3: Self-Host with Docker Build

1. Clone this repository:
   ```bash
   git clone https://github.com/AsunaPahlo/armada-web.git
   cd armada-web
   ```

2. Edit `docker-compose.yml` and set a secure `SECRET_KEY` (see [Configuration](#configuration))

3. Start the server:
   ```bash
   docker compose up -d
   ```

4. Access the dashboard at `http://localhost:5000`

5. Create an account and generate API keys for your game clients

### Option 4: Manual Installation

<details>
<summary>Click to expand</summary>

#### Prerequisites
- Python 3.12+

#### Steps

1. Clone the repository:
   ```bash
   git clone https://github.com/AsunaPahlo/armada.git
   cd armada
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Run the server:
   ```bash
   SECRET_KEY="your-secret-key-here" python run.py
   ```

</details>

## Plugin Installation

Once your server is running, install the Dalamud plugin to start sending data:


1. Open the Plugin Installer in-game: `/xlplugins`
2. Search for **"Armada"** and install
3. Open plugin settings: `/armada`
4. Enter your server URL and API key

For detailed plugin configuration, see the [Plugin README](plugin/Armada/README.md).

## Configuration

Configuration is handled through the `docker-compose.yml` file:

```yaml
services:
  armada:
    image: asunapahlo/armada:latest
    container_name: armada
    restart: unless-stopped
    ports:
      - "5000:5000"  # Change the first port to use a different external port
    volumes:
      - armada_data:/app/data  # Persistent storage for database
    environment:
      - SECRET_KEY=change-this-to-a-random-secret-key  # Required: set a secure key

volumes:
  armada_data:
```

> **Important:** Change `SECRET_KEY` to a random string. You can generate one with: `openssl rand -hex 32`

### Generating API Keys

1. Log in to the Armada dashboard
2. Click the **Settings** icon in the top right
3. Select **API Keys**
4. Create a new key for each game client

> **Tip:** Use descriptive names like "Main Account" or "Alt FC" to identify which client is sending data.

## Exposing to the Internet

To connect game clients from outside your local network, you'll need to expose the server. Some options:

- **Reverse Proxy** — Use nginx or Caddy with SSL (recommended)
- **Cloudflare Tunnel** — Free, secure tunnel without port forwarding
- **Port Forwarding** — Forward port 5000 on your router (not recommended without SSL)

Example nginx configuration:

```nginx
server {
    listen 443 ssl http2;
    server_name armada.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Screenshots

*Coming soon*

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Disclaimer

FINAL FANTASY XIV is a registered trademark of Square Enix Holdings Co., Ltd. Armada is not affiliated with or endorsed by Square Enix.
