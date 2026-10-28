"""IPv4 internet counters and shared daily upload+download quotas.

An independent nftables table survives hotspot teardown. Named counters
survive rule/address changes. Only explicitly selected devices get quotas.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from zoneinfo import ZoneInfo

TABLE = 'whoson_usage'


def device_key(device):
    return 'pc-' + device.client_id if device.source == 'cable' else device.mac.lower()


def counter_name(key, direction):
    return direction + '_' + hashlib.sha256(key.encode()).hexdigest()[:24]


def parse_gb(value):
    try:
        number = Decimal(value)
        if not number.is_finite() or not 0 < number <= 1_000_000:
            raise ValueError
        amount = int(number * 1_000_000_000)
        if amount < 1:
            raise ValueError
        return amount
    except (InvalidOperation, ValueError):
        raise ValueError('enter a positive daily allowance in GB, such as 2 or 0.5') from None


def human_bytes(value):
    for divisor, unit in ((1e9, 'GB'), (1e6, 'MB'), (1e3, 'KB')):
        if value >= divisor:
            return f'{value/divisor:.1f} {unit}'
    return f'{value:.0f} B'


class Kernel:
    def __init__(self, iface, subnet=None):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', iface):
            raise ValueError('invalid network interface')
        self.iface = iface
        self.subnet = str(ipaddress.IPv4Network(subnet, strict=False)) if subnet else None
        self.exhausted = set()
        self.quotas = set()

    def _run(self, args, script=None):
        argv = ['nft'] + args
        if os.geteuid() != 0:
            argv = ['sudo', '-n'] + argv
        return subprocess.run(argv, input=script, capture_output=True, text=True, timeout=10)

    def read(self):
        result = self._run(['-j', 'list', 'table', 'inet', TABLE])
        if result.returncode:
            if 'No such file or directory' in result.stderr:
                self.quotas = set()
                return {}
            raise RuntimeError('usage counters need admin rights: ' + result.stderr.strip())
        counters = {}
        self.exhausted = set()
        self.quotas = set()
        for item in json.loads(result.stdout).get('nftables', []):
            if 'counter' in item:
                obj = item['counter']
                counters[obj['name']] = int(obj.get('bytes', 0))
            if 'quota' in item:
                quota = item['quota']
                self.quotas.add(quota['name'])
                if quota.get('used', 0) >= quota.get('bytes', 1):
                    self.exhausted.add(quota['name'])
        return counters

    def install(self, devices, records, counters, reset=False):
        lines = [f'add table inet {TABLE}']
        if reset:
            lines += [f'delete table inet {TABLE}', f'add table inet {TABLE}']
            counters = {}
            self.quotas = set()
        lines += [f'add chain inet {TABLE} forward {{ type filter hook forward priority 10; policy accept; }}',
                  f'flush chain inet {TABLE} forward']
        # Quotas are shared across both directions and seeded with today's
        # total, so changing an allowance never grants a fresh allowance.
        for quota in sorted(self.quotas):
            lines.append(f'delete quota inet {TABLE} {quota}')
        quotas = set()
        for key, row in sorted(records.items()):
            for direction in ('down', 'up'):
                name = counter_name(key, direction)
                if name not in counters:
                    lines.append(f'add counter inet {TABLE} {name} {{ packets 0 bytes {int(row[direction])}; }}')
            if row.get('limit'):
                quota = counter_name(key, 'quota')
                quotas.add(quota)
                lines.append(f'add quota inet {TABLE} {quota} {{ over {int(row["limit"])} bytes used {int(row["down"]+row["up"])} bytes; }}')
        import scanner
        subnet = self.subnet or str(ipaddress.IPv4Network(scanner.autodetect_subnet(), strict=False))
        local = '{ ' + ', '.join(sorted({subnet, '10.42.0.0/24'})) + ' }'
        for key, ip, source in devices:
            ip = str(ipaddress.IPv4Address(ip))
            iface = 'ap0' if source == 'booth' else self.iface
            for direction, match in (
                ('up', f'iifname "{iface}" ip saddr {ip} ip daddr != {local}'),
                ('down', f'oifname "{iface}" ip daddr {ip} ip saddr != {local}'),
            ):
                prefix = f'add rule inet {TABLE} forward {match}'
                if records[key].get('limit'):
                    lines.append(prefix + f' quota name {counter_name(key, "quota")} drop')
                lines.append(prefix + f' counter name {counter_name(key, direction)}')
        result = self._run(['-f', '-'], '\n'.join(lines) + '\n')
        if result.returncode:
            raise RuntimeError('could not install usage/quota rules: ' + result.stderr.strip())
        self.quotas = quotas
        self.exhausted = {counter_name(k, "quota") for k, row in records.items()
                          if row.get("limit") and row["down"]+row["up"] >= row["limit"]}


class Monitor:
    def __init__(self, path, kernel, timezone="Africa/Cairo"):
        self.timezone = ZoneInfo(timezone)
        self.path = Path(path)
        self.kernel = kernel
        self.lock = threading.RLock()
        self.state = {'day': '', 'records': {}}
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        self.previous = {}
        self.last_time = None
        self.signature = None

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(self.state, handle)
        os.replace(temporary, self.path)

    def set_limit(self, key, limit):
        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            raise ValueError('daily allowance must be positive')
        with self.lock:
            row = self.state['records'].setdefault(key, {'down': 0, 'up': 0})
            row['limit'] = limit
            self.signature = None
            self._save()

    def update(self, devices, day=None, now=None):
        day = day or datetime.now(self.timezone).date().isoformat()
        now = time.monotonic() if now is None else now
        with self.lock:
            raw = self.kernel.read()
            records = self.state['records']
            reset = bool(self.state['day'] and self.state['day'] != day)
            if reset:
                for row in records.values():
                    row.update(down=0, up=0)
                self.previous = {}
                self.last_time = None
            if not reset:
                for key, row in records.items():
                    for direction in ('down', 'up'):
                        row[direction] = max(row[direction], raw.get(counter_name(key, direction), 0))
            active = {}
            for device in devices:
                if device.source not in ('booth', 'cable') or not device.ip:
                    continue
                key = device_key(device)
                if key:
                    records.setdefault(key, {'down': 0, 'up': 0, 'limit': None})
                    active[key] = (key, device.ip, device.source)
            desired = sorted(active.values())
            signature = (day, tuple(desired), tuple((k, r.get('limit')) for k, r in sorted(records.items())))
            missing = any(counter_name(k, d) not in raw for k in records for d in ('down', 'up'))
            if reset or missing or signature != self.signature:
                self.kernel.install(desired, records, raw, reset=reset)
                self.signature = signature
            self.state['day'] = day
            elapsed = now-self.last_time if self.last_time is not None else 0
            for device in devices:
                if device.source not in ('booth', 'cable') or not device.ip:
                    continue
                key = device_key(device)
                if key not in active:
                    continue
                row = records[key]
                old = self.previous.get(key)
                device.download_now = max(0, row['down']-old[0])/elapsed if old and elapsed > 0 else 0
                device.upload_now = max(0, row['up']-old[1])/elapsed if old and elapsed > 0 else 0
                device.used_down, device.used_up = row['down'], row['up']
                device.daily_limit = row.get('limit')
                device.quota_exhausted = bool(row.get('limit') and (row['down']+row['up'] >= row['limit'] or
                    counter_name(key, 'quota') in getattr(self.kernel, 'exhausted', set())))
            self.previous = {k: (r['down'], r['up']) for k, r in records.items()}
            self.last_time = now
            self._save()
