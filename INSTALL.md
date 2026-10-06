# Installing on another machine

These steps work on Windows and Linux. The target machine needs nothing pre-installed:
[uv](https://docs.astral.sh/uv/) downloads Python itself, and ffmpeg comes from a pip
package.

## 1. Copy the project

Copy these to the target machine (git, zip, or scp):

```
pyproject.toml  uv.lock  README.md  run.bat  run.sh  src/  static/
models/        # optional: ~75MB; without it the server downloads it on first start
```

Don't copy `.venv/`. It contains machine-specific paths and won't work on another
machine; `uv sync` recreates it.

## 2. Install and run

**Windows:** double-click `run.bat`. It installs uv if needed, runs `uv sync --frozen`, and starts the server on port 8123 (set `PORT` to change it). Or by hand in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
cd C:\deploy\phostt-server
uv sync --frozen
uv run src/main.py --port 8123
```

**Linux:** run `./run.sh` (same steps as `run.bat`; set `PORT` to change the port). Or by hand:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /opt/phostt-server
uv sync --frozen
uv run src/main.py --port 8123
```

`--frozen` installs exactly the versions in `uv.lock`, so the target gets the same
packages that were tested.

Then:

- Open port 8123 in the firewall.
- Check that it's up: `curl http://<server-ip>:8123/health`.
- If browsers on other machines need the mic test page, create a certificate on the
  target and start with HTTPS:

  ```bash
  uv run src/make_cert.py
  uv run src/main.py --port 8123 --ssl-certfile cert.pem --ssl-keyfile key.pem
  ```

Settings such as `NUM_THREADS` and `DECODING_METHOD` are environment variables; see
the Configuration table in [README.md](README.md).

## 3. Keep it running after reboot

### Linux (systemd)

Create `/etc/systemd/system/phostt-stt.service`, replacing `<user>` with the account
that installed uv:

```ini
[Unit]
Description=phostt STT server
After=network-online.target

[Service]
WorkingDirectory=/opt/phostt-server
ExecStart=/home/<user>/.local/bin/uv run --frozen src/main.py --port 8123
Environment=NUM_THREADS=4
Restart=always
User=<user>

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl enable --now phostt-stt
journalctl -u phostt-stt -f    # follow the logs
```

### Windows (NSSM)

[NSSM](https://nssm.cc/) runs a command as a Windows service:

```powershell
nssm install phostt-stt "C:\Users\<user>\.local\bin\uv.exe" "run --frozen src/main.py --port 8123"
nssm set phostt-stt AppDirectory C:\deploy\phostt-server
nssm start phostt-stt
```

Without NSSM, a Task Scheduler task set to run "At startup" with the same command and
working directory also works.

## Machines without internet access

`uv sync` downloads Python and all packages, and the first start downloads the model,
so an offline machine needs those files brought in first. On a machine with internet,
download the packages for the target OS into a folder. Copy that folder over, along
with uv's Python install and the `models/` folder, then run `uv sync --offline`
pointed at it. There is no script for this yet.
