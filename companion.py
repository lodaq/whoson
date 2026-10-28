"""Authenticated LAN discovery for the Windows helper (UDP, no IP setup).

Only a helper carrying this laptop's exported key can register. Responses
are signed and echo a fresh nonce; receiving a packet never runs its text.
"""
import base64
import gzip
import hashlib
import hmac
import ipaddress
import re
import socket
import sys
import threading
import time
from pathlib import Path

PORT = 47831


class Discovery:
    def __init__(self, key, booth):
        self.key = bytes.fromhex(key)
        self.booth = booth
        self.seen = {}

    def reply(self, raw, peer_ip, now=None):
        now = time.time() if now is None else now
        if len(raw) > 1024:
            return None
        try:
            text = raw.decode('ascii')
            body, signature = text.rsplit('|', 1)
            expected = hmac.new(self.key, body.encode('ascii'), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            kind, version, stamp, nonce, client, name, mac, client_ip = body.split('|')
            if kind != 'discover' or version != '1' or abs(now-int(stamp)) > 60:
                return None
            if not all(re.fullmatch(r'[a-f0-9]{32}', v) for v in (nonce, client)):
                return None
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,63}', name):
                return None
            if not re.fullmatch(r'(?:[a-f0-9]{2}:){5}[a-f0-9]{2}', mac):
                return None
            ipaddress.IPv4Address(peer_ip)
            if client_ip != peer_ip:
                return None
        except (ValueError, UnicodeError):
            return None
        self.seen = {n: t for n, t in self.seen.items() if now-t < 120}
        if nonce in self.seen:
            return None
        if len(self.seen) >= 256:
            return None
        self.seen[nonce] = now
        gateway = self.booth.register_pc(client, peer_ip, name, mac)
        if not gateway:
            return None
        body = f'ready|1|{nonce}|{gateway}'
        signature = hmac.new(self.key, body.encode('ascii'), hashlib.sha256).hexdigest()
        return f'{body}|{signature}'.encode('ascii')


class Server(threading.Thread):
    def __init__(self, key, booth, updates):
        super().__init__(daemon=True)
        self.protocol = Discovery(key, booth)
        self.updates = updates
        self.stopping = threading.Event()

    def stop(self):
        self.stopping.set()

    def run(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind(('', PORT))
                sock.settimeout(1)
                while not self.stopping.is_set():
                    try:
                        raw, peer = sock.recvfrom(2048)
                    except socket.timeout:
                        try:
                            self.protocol.booth.expire_pcs()
                        except Exception as error:
                            self.updates.put(("error", f"Windows helper cleanup: {error}"))
                        continue
                    try:
                        reply = self.protocol.reply(raw, peer[0])
                        if reply:
                            sock.sendto(reply, peer)
                    except Exception as error:
                        self.updates.put(('error', f'Windows helper: {error}'))
        except OSError as error:
            self.updates.put(('error', f'Windows discovery unavailable: {error}'))


def setup_command(key):
    """One paste into PowerShell; carries the full paired helper offline.

    The short bootstrap expands our compressed script to a random temporary
    file. Its installer requests elevation, copies itself to ProgramData,
    and installs the startup task before the bootstrap removes that file.
    """
    if not re.fullmatch(r'[a-f0-9]{64}', key):
        raise ValueError('invalid pairing key')
    source = Path(__file__).parent / 'windows'
    if not source.is_dir():
        source = Path(sys.prefix) / "share" / "whoson" / "windows"
    script = (source / 'point-to-laptop.ps1').read_text(encoding='utf-8-sig')
    script = script.replace('__WHOSON_PAIRING_KEY__', key)
    payload = base64.b64encode(gzip.compress(script.encode('utf-8-sig'), mtime=0)).decode('ascii')
    return (
        "& { $ErrorActionPreference='Stop'; "
        "$p=Join-Path ([IO.Path]::GetTempPath()) ('whoson-'+[Guid]::NewGuid().ToString('N')+'.ps1'); "
        "$s=New-Object IO.MemoryStream(,[Convert]::FromBase64String('" + payload + "')); "
        "$g=New-Object IO.Compression.GZipStream($s,[IO.Compression.CompressionMode]::Decompress); "
        "$m=New-Object IO.MemoryStream; try { $g.CopyTo($m); "
        "[IO.File]::WriteAllBytes($p,$m.ToArray()); "
        "& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p -Action install; "
        "if ($LASTEXITCODE -ne 0) { throw 'Windows setup did not complete.' } "
        "} finally { $g.Dispose(); $s.Dispose(); $m.Dispose(); "
        "Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue } }"
    )


def save_installer(path, key):
    """A single double-clickable Windows file, including its pairing key."""
    command = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "' + setup_command(key) + '"'
    if len(command) > 8191:
        raise ValueError('Windows installer exceeds the command-line limit')
    script = ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n' + command +
              '\r\nset "result=%ERRORLEVEL%"\r\n'
              'if not "%result%"=="0" echo Windows setup failed. See the error above.\r\n'
              'pause\r\nexit /b %result%\r\n')
    path = Path(path)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_bytes(script.encode('ascii'))
