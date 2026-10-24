---
summary: "Secure the dashboard with SSH tunneling; configure Docker auto-restart."
description: "Deploy Dango Discord AI bot to a VPS with Docker. Includes SSH tunneling to secure the web dashboard, systemd service setup, and firewall configuration."
tags:
  - Advanced
  - VPS
  - Deployment
  - Self-hosting
---

# VPS Deployment

The Docker setup works on any VPS. The one thing to be careful about: **the web dashboard has no login screen**.

## Secure the dashboard port

Do **not** open port `17860` in your VPS firewall. Anyone who can reach it can read and change your Discord token and API keys.

The bundled `docker-compose.yml` already publishes the port on `127.0.0.1` only, so it is unreachable from outside the VPS. Keep it that way: a firewall alone is not enough, because ports Docker publishes bypass host firewalls such as UFW.

::: warning Upgrading from an older docker-compose.yml
Older copies of the file published the port as `"17860:17860"`, which listens on every network interface. Change that line to:

```yaml
    ports:
      - "127.0.0.1:17860:17860"
```

then run `docker compose up -d`.
:::

To reach the dashboard from your own computer, use an SSH tunnel:

```bash
ssh -L 17860:localhost:17860 user@your-vps-ip
```

Open `http://localhost:17860` in your browser — traffic goes through SSH to your VPS. The port never touches the public internet.

To run the tunnel in the background:

```bash
ssh -fNL 17860:localhost:17860 user@your-vps-ip
```

`-f` sends it to the background; `-N` means "don't run any commands, just forward the port."

## Keeping the bot running

Docker containers stop when the VPS reboots unless you configure Docker to start on login, or use a systemd service. The simplest approach:

```bash
# After reboot, cd to the folder with docker-compose.yml and run:
docker compose start
```

For a production setup, add a `restart` policy to each service in `docker-compose.yml`. Open the file and add `restart: unless-stopped` under each service name:

```yaml
services:
  bot:
    restart: unless-stopped   # add this line
    image: ...
  web:
    restart: unless-stopped   # add this line
    image: ...
```

With `unless-stopped`, containers restart automatically after a reboot unless you explicitly stopped them with `docker compose stop`.
