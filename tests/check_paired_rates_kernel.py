"""Exact paired-PC rates over one-interface NAT; no host network changes.
Run: unshare -Urn python3 -m tests.check_paired_rates_kernel
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import commands
import usage
from watch import Device


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def node():
    process = subprocess.Popen(['unshare', '-n', 'sleep', '90'])
    for _ in range(100):
        if os.stat(f'/proc/{process.pid}/ns/net').st_ino != os.stat('/proc/self/ns/net').st_ino:
            return process
        time.sleep(.01)
    process.terminate()
    raise RuntimeError('network namespace did not start')


def check():
    pc, router = node(), node()
    server = None
    p = ('nsenter', '-t', str(pc.pid), '-n')
    r = ('nsenter', '-t', str(router.pid), '-n')
    try:
        for interface, peer, process in (('gw0', 'uplink0', router), ('pcwire0', 'eth0', pc)):
            run('ip', 'link', 'add', interface, 'type', 'veth', 'peer', 'name', peer)
            run('ip', 'link', 'set', peer, 'netns', str(process.pid))
        run('ip', 'link', 'set', 'pcwire0', 'netns', str(router.pid))
        run(*r, 'ip', 'link', 'add', 'br0', 'type', 'bridge')
        for name in ('uplink0', 'pcwire0'):
            run(*r, 'ip', 'link', 'set', name, 'master', 'br0')
            run(*r, 'ip', 'link', 'set', name, 'up')
        run(*r, 'ip', 'addr', 'add', '192.168.1.1/24', 'dev', 'br0')
        run(*r, 'ip', 'link', 'set', 'br0', 'up')
        run(*r, 'ip', 'link', 'set', 'lo', 'up')
        run(*r, 'ip', 'addr', 'add', '198.51.100.2/32', 'dev', 'lo')
        run(*p, 'ip', 'addr', 'add', '192.168.1.20/24', 'dev', 'eth0')
        run(*p, 'ip', 'link', 'set', 'eth0', 'up')
        run('ip', 'addr', 'add', '192.168.1.253/24', 'dev', 'gw0')
        run('ip', 'link', 'set', 'gw0', 'up')
        run('ip', 'route', 'add', 'default', 'via', '192.168.1.1')
        run(*p, 'ip', 'route', 'add', 'default', 'via', '192.168.1.253')
        for command in commands.lan_forwarding_cmds('gw0') + commands.nft_lan_prepare_cmds() + commands.lan_nat_cmds('192.168.1.20'):
            run(*command)
        # The server emits a different payload size in each direction, making
        # swapped labels and aggregate interface counters fail this check.
        server = subprocess.Popen([*r, sys.executable, '-u', '-c', '''
import socket,select
sockets=[]
for ip in ('198.51.100.2','192.168.1.1'):
 s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind((ip,9000));sockets.append(s)
print('ready',flush=True)
while True:
 for s in select.select(sockets,[],[])[0]:
  data,peer=s.recvfrom(2048)
  s.sendto(b'd'*1300,peer)
'''], stdout=subprocess.PIPE, text=True)
        assert server.stdout.readline().strip() == 'ready'
        with tempfile.TemporaryDirectory() as folder:
            monitor = usage.Monitor(Path(folder)/'usage.json', usage.Kernel('gw0', '192.168.1.0/24'))
            device = Device('192.168.1.20', 'aa:bb:cc:dd:ee:ff', source='cable', client_id='12'*16)
            monitor.update([device], now=0)

            def traffic(destination):
                run(*p, sys.executable, '-c', '''
import socket,sys
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(3)
for _ in range(7):
 s.sendto(b'u'*900,(sys.argv[1],9000))
 assert len(s.recv(2048))==1300
''', destination)

            traffic('198.51.100.2')
            monitor.update([device], now=2)
            # IPv4 (20) + UDP (8) headers count as network bytes.
            assert device.used_up == 7*(900+28), device.used_up
            assert device.used_down == 7*(1300+28), device.used_down
            assert device.upload_now == 3248, device.upload_now
            assert device.download_now == 4648, device.download_now
            traffic('192.168.1.1')  # Local LAN traffic must not count.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as own:
                own.settimeout(3)
                own.sendto(b'laptop', ('198.51.100.2',9000))
                own.recv(2048)
            monitor.update([device], now=3)
            assert device.upload_now == device.download_now == 0
            assert device.used_up == 6496 and device.used_down == 9296
            monitor.last_time = None
            monitor.previous = {}
            monitor.update([device])
            baseline = monitor.last_time
            traffic('198.51.100.2')
            monitor.update([device])
            elapsed = monitor.last_time - baseline
            assert elapsed > 0
            assert device.upload_now == 6496 / elapsed
            assert device.download_now == 9296 / elapsed
            print(f'PASS: actual monotonic sample interval {elapsed:.4f} s, both directional rates equal measured bytes / elapsed time.')
            print('PASS: one-arm NAT paired PC: upload 6496 B, download 9296 B; exact rates 3248/4648 B/s over 2 s; idle, local and laptop traffic excluded.')
    finally:
        for process in (server, pc, router):
            if process is not None:
                process.terminate()
                process.wait()


if __name__ == '__main__':
    check()
