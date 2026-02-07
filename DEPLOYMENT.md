# Deployment Guide

This project includes scripts to run the API as a background service on Windows or Linux.

## Windows (Service)
From PowerShell:
```powershell
cd deploy
.\install.ps1 -ServiceName "multilingual-bot" -Port 9019
```

Uninstall:
```powershell
cd deploy
.\uninstall.ps1 -ServiceName "multilingual-bot"
```

Status:
```powershell
cd deploy
.\status.ps1 -ServiceName "multilingual-bot"
```

## Linux (systemd)
From a Linux shell:
```bash
cd deploy
sudo chmod +x install.sh
sudo ./install.sh
```

Uninstall:
```bash
cd deploy
sudo chmod +x uninstall.sh
sudo ./uninstall.sh
```

Status:
```bash
cd deploy
sudo chmod +x status.sh
sudo ./status.sh
```

## Notes
- Configure `configs/settings.json` before installing.
- Use `ENV_FILE` to load environment variables in systemd.
- `deploy/README.md` contains full options and parameters.
