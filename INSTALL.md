# Installing on another machine

The target machine needs nothing pre-installed: [uv](https://docs.astral.sh/uv/)
downloads Python 3.12 itself, and ffmpeg comes from a pip package. The run scripts
install uv if it's missing.

## 1. Copy the project

Copy these to the target machine (git, zip, or scp):

```
pyproject.toml  uv.lock  .python-version  README.md  hotwords.txt  .env.example
run-phostt-server.bat  run-phostt-server.sh  install-phostt-service.sh
src/  static/
models/        # optional: ~75MB; without it the server downloads it on first start
```

Don't copy `.venv/`. It contains machine-specific paths and won't work on another
machine; `uv sync` recreates it.

## 2. Configure (optional)

All settings are environment variables with sensible defaults. To change any of them,
copy `.env.example` to `.env` and uncomment the lines you need, for example:

```ini
PORT=8123
NUM_THREADS=4
```

The run scripts and the Linux service load `.env` automatically. Variables already set
in the shell take precedence over `.env`. See the Configuration table in
[README.md](README.md) for what each setting does.

`.env` is in `.gitignore`; keep it out of git.

---

## Windows

### Install and run

Double-click `run-phostt-server.bat`. It:

1. installs uv to `%USERPROFILE%\.local\bin` if it isn't found,
2. runs `uv sync --frozen` (downloads Python and the exact package versions in `uv.lock`),
3. starts the server with `.env` loaded, on port 8123 by default.

Or by hand in PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
cd C:\deploy\phostt-server
uv sync --frozen
uv run --frozen --env-file .env src/main.py    # drop --env-file .env if you have no .env
```

### Open the firewall and check it

In an elevated PowerShell:

```powershell
New-NetFirewallRule -DisplayName "phostt STT" -Direction Inbound -Protocol TCP -LocalPort 8123 -Action Allow
```

From another machine: `curl http://<server-ip>:8123/health`.

### HTTPS (needed for the mic test page from other machines)

Browsers only allow the microphone on `https://` pages or `http://localhost`.

```powershell
uv run src/make_cert.py                  # add extra hostnames/IPs as arguments if needed
```

This writes `cert.pem` and `key.pem` to the project folder. Then add to `.env`:

```ini
SSL_CERTFILE=cert.pem
SSL_KEYFILE=key.pem
```

Re-run `make_cert.py` if the machine's IP changes.

### Keep it running after reboot

**NSSM (Windows service).** [NSSM](https://nssm.cc/) runs a command as a service. In an
elevated prompt, replacing `<user>` with the account that installed uv:

```powershell
nssm install phostt-stt "C:\Users\<user>\.local\bin\uv.exe" "run --frozen --env-file .env src/main.py"
nssm set phostt-stt AppDirectory C:\deploy\phostt-server
nssm set phostt-stt ObjectName ".\<user>" "<password>"
nssm set phostt-stt AppStdout C:\deploy\phostt-server\server.log
nssm set phostt-stt AppStderr C:\deploy\phostt-server\server.log
nssm start phostt-stt
```

Running the service as the same user that ran `uv sync` (`ObjectName`) lets it reuse
the Python that uv already downloaded. Under the default LocalSystem account, uv would
download it again into the system profile.

Manage it with `nssm restart phostt-stt`, `nssm stop phostt-stt`, `nssm remove phostt-stt confirm`.

**Task Scheduler (no extra tools).** Run the batch file at startup:

```powershell
schtasks /Create /TN phostt-stt /SC ONSTART /RU <user> /RP * /TR "C:\deploy\phostt-server\run-phostt-server.bat"
```

`/RP *` prompts for the account's password so the task runs without anyone logged in.

---

## Linux

### Install and run

```bash
cd /opt/phostt-server
chmod +x run-phostt-server.sh install-phostt-service.sh   # if copied via zip
./run-phostt-server.sh
```

It does the same as the Windows script: installs uv to `~/.local/bin` if needed, runs
`uv sync --frozen`, and starts the server with `.env` loaded.

Or by hand:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd /opt/phostt-server
uv sync --frozen
uv run --frozen --env-file .env src/main.py    # drop --env-file .env if you have no .env
```

### Open the firewall and check it

```bash
sudo ufw allow 8123/tcp                                   # Ubuntu/Debian with ufw
# or: sudo firewall-cmd --add-port=8123/tcp --permanent && sudo firewall-cmd --reload
curl http://<server-ip>:8123/health
```

### HTTPS (needed for the mic test page from other machines)

```bash
uv run src/make_cert.py                  # add extra hostnames/IPs as arguments if needed
```

Then add `SSL_CERTFILE=cert.pem` and `SSL_KEYFILE=key.pem` to `.env`, as on Windows.

### Keep it running after reboot (systemd)

Run the install script as the account that ran `uv sync` (not with `sudo`; it asks for
your password when it needs root):

```bash
./install-phostt-service.sh
```

It writes `/etc/systemd/system/phostt-stt-server.service`, then enables and starts it.
The service runs as the current user, from the folder the script is in, with that
user's uv, and loads `.env` from that folder. Run `./run-phostt-server.sh` once first so
uv is installed. Re-run the install script if you move the folder.

Manage it with:

```bash
systemctl status phostt-stt-server
sudo systemctl restart phostt-stt-server
journalctl -u phostt-stt-server -f        # follow the logs
```

After editing `.env`, restart the service to apply the change.

---

## Machines without internet access

`uv sync` downloads Python and all packages, and the first start downloads the model,
so an offline machine needs those files brought in first. On a machine with internet
running the same OS, download the packages into a folder. Copy that folder over, along
with uv's Python install and the `models/` folder, then run `uv sync --offline`
pointed at it. There is no script for this yet.
