"""deploy/aws-ec2 — the single-EC2 pilot files keep their safety properties."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy" / "aws-ec2"
FILES = sorted(p for p in DEPLOY.iterdir() if p.is_file())


def _text(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """The file without its comment lines (comments may name what is forbidden)."""
    return "\n".join(
        line for line in _text(name).splitlines() if not line.lstrip().startswith("#")
    )


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_deploy_files_use_lf_line_endings(path):
    """bash and systemd reject CRLF; a Windows checkout must not break them."""
    assert b"\r\n" not in path.read_bytes()


def test_app_listens_on_loopback_only():
    unit = _text("smartvoice.service")
    assert "--server.address 127.0.0.1" in unit
    assert "streamlit run Home.py" in unit
    assert "User=smartvoice" in unit
    assert "--browser.gatherUsageStats false" in unit


def test_app_can_write_only_its_data_and_env():
    unit = _text("smartvoice.service")
    assert "ProtectSystem=strict" in unit
    paths = re.search(r"^ReadWritePaths=(.+)$", unit, re.M).group(1).split()
    assert paths == ["/opt/smartvoice/app/data", "/opt/smartvoice/app/.env"]


def test_caddy_proxies_to_the_app_over_https_only():
    caddy = _text("Caddyfile.template")
    assert "reverse_proxy 127.0.0.1:8501" in caddy
    assert "__DOMAIN__ {" in caddy
    assert "Strict-Transport-Security" in caddy
    assert "http://" not in caddy


def test_installer_never_uses_the_published_password():
    install = _code("install.sh")
    assert "admin1234" not in install
    assert "SMARTVOICE_BOOTSTRAP_PASSWORD" in install
    assert "secrets.token_urlsafe" in install
    # The first-install branch only runs when there is no .env yet.
    assert 'if [[ ! -f "$APP/.env" ]]' in install
    assert "chmod 0600" in install


def test_installer_keeps_data_and_env_on_update():
    install = _text("install.sh")
    rsync = install[install.index("rsync -a --delete"):]
    rsync = rsync[: rsync.index('"$SRC_DIR/" "$APP/"')]
    for protected in ("'/data/'", "'/.env'", "'/.git/'"):
        assert f"--exclude {protected}" in rsync
    # rsync uses the first matching rule: the include must precede '/.env.*'.
    assert rsync.index("--include '/.env.example'") < rsync.index("--exclude '/.env.*'")
    assert "--delete-excluded" not in rsync


def test_installer_validates_its_arguments():
    install = _text("install.sh")
    assert "set -euo pipefail" in install
    assert '[[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]' in install
    assert "EUID" in install


def test_backup_uses_the_checked_snapshot_and_encrypts_uploads():
    backup = _code("backup.sh")
    assert "scripts/backup_db.py" in backup
    assert backup.count("--sse AES256") == 2
    assert "--delete" not in backup


def test_backup_timer_catches_up_after_a_stopped_instance():
    timer = _text("smartvoice-backup.timer")
    assert "Persistent=true" in timer
    assert "OnCalendar=" in timer


def test_units_point_at_installed_paths():
    assert "ExecStart=/opt/smartvoice/app/deploy/aws-ec2/backup.sh" in _text("smartvoice-backup.service")
    assert "WorkingDirectory=/opt/smartvoice/app" in _text("smartvoice.service")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.parametrize("script", ["install.sh", "backup.sh"])
def test_shell_scripts_parse(script):
    result = subprocess.run(["bash", "-n", str(DEPLOY / script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_gitattributes_pins_lf_for_deploy_files():
    attributes = (DEPLOY.parent.parent / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    assert "deploy/** text eol=lf" in attributes
