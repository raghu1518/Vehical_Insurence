# Deployment (Windows Service)

These scripts install/uninstall the bot as a Windows service using `sc.exe`.

## Install
```powershell
cd deploy
.\install.ps1 -ServiceName "multilingual-bot" -Port 9019
```

Optional params:
- `-Host` (default `0.0.0.0`)
- `-Port`
- `-DisplayName`
- `-Python` (full path to python.exe)
- `-WorkingDir` (project root)

The installer will:
1. Create `.venv` (if missing)
2. Install dependencies
3. Create/update the Windows service
4. Configure auto-restart on failure
5. Start the service

## Uninstall
```powershell
cd deploy
.\uninstall.ps1 -ServiceName "multilingual-bot"
```

## Status
```powershell
cd deploy
.\status.ps1 -ServiceName "multilingual-bot"
```

Notes:
- Configure your settings in `configs/settings.json` before installing.
- If you need environment variables, set them at the system level or inside the service account.

---

# Deployment (Linux systemd)

These scripts install/uninstall the bot as a systemd service.

## Install
```bash
cd deploy
sudo chmod +x install.sh
sudo ./install.sh
```

Optional env vars:
- `SERVICE_NAME` (default `multilingual-bot`)
- `DISPLAY_NAME` (default `Multilingual Multi-Agent Bot`)
- `HOST` (default `0.0.0.0`)
- `PORT` (default `9019`)
- `WORKING_DIR` (project root)
- `PYTHON` (full path to python binary)
- `RUN_USER` (linux user to run service; defaults to sudo user)
- `ENV_FILE` (absolute path to systemd EnvironmentFile)

Example:
```bash
sudo SERVICE_NAME=multilingual-bot PORT=9019 ./install.sh
```

The installer will:
1. Create `.venv` (if missing)
2. Install dependencies
3. Create/update the systemd unit
4. Enable + restart the service

## Uninstall
```bash
cd deploy
sudo chmod +x uninstall.sh
sudo ./uninstall.sh
```

## Status
```bash
cd deploy
sudo chmod +x status.sh
sudo ./status.sh
```

Notes:
- Configure settings in `configs/settings.json` before installing.
- If you need environment variables, set `ENV_FILE` to an absolute path (systemd `EnvironmentFile`).
