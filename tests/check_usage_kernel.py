"""Real packet test, isolated from the host network.
Run: unshare -Urn python3 -m tests.check_usage_kernel
Requires Linux user/network namespaces, nft, ip, nsenter and ping.
"""
import os
import subprocess
import time

import usage


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def node():
    process = subprocess.Popen(['unshare', '-n', 'sleep', '90'])
    for _ in range(100):
        if os.stat(f'/proc/{process.pid}/ns/net').st_ino != os.stat('/proc/self/ns/net').st_ino:
            return process
        time.sleep(.01)
    raise RuntimeError('network namespace did not start')


pc = node()
wan = node()
try:
    for interface, peer, process, gateway, address in (
        ('ap0', 'client0', pc, '10.42.0.1/24', '10.42.0.7/24'),
        ('wan0', 'remote0', wan, '198.51.100.1/24', '198.51.100.2/24'),
    ):
        run('ip', 'link', 'add', interface, 'type', 'veth', 'peer', 'name', peer)
        run('ip', 'link', 'set', peer, 'netns', str(process.pid))
        run('ip', 'addr', 'add', gateway, 'dev', interface)
        run('ip', 'link', 'set', interface, 'up')
        prefix = ('nsenter', '-t', str(process.pid), '-n')
        run(*prefix, 'ip', 'addr', 'add', address, 'dev', peer)
        run(*prefix, 'ip', 'link', 'set', peer, 'up')
        run(*prefix, 'ip', 'route', 'add', 'default', 'via', gateway.split('/')[0])
    run('sysctl', '-q', '-w', 'net.ipv4.ip_forward=1')
    key = 'aa:bb:cc:dd:ee:ff'
    kernel = usage.Kernel('wan0', '192.168.1.0/24')
    devices = [(key, '10.42.0.7', 'booth')]
    records = {key: {'down': 0, 'up': 0, 'limit': 800}}
    kernel.install(devices, records, kernel.read())

    def ping(count):
        return subprocess.run(['nsenter', '-t', str(pc.pid), '-n', 'ping',
                               '-c', str(count), '-i', '.02', '-W', '1',
                               '198.51.100.2'], capture_output=True, text=True)

    result = ping(10)
    totals = kernel.read()
    assert sum(totals.values()) <= 800, (totals, result.stdout)
    assert all(value > 0 for value in totals.values()), (totals, result.stdout)
    assert usage.counter_name(key, 'quota') in kernel.exhausted
    blocked = ping(1)
    assert blocked.returncode != 0, blocked.stdout
    assert kernel.read() == totals, 'blocked packets must not count as data used'

    run('nsenter', '-t', str(pc.pid), '-n', 'ip', 'addr', 'add', '10.42.0.8/24', 'dev', 'client0')
    other = subprocess.run(['nsenter', '-t', str(pc.pid), '-n', 'ping', '-I', '10.42.0.8',
                            '-c', '1', '-W', '1', '198.51.100.2'], capture_output=True)
    assert other.returncode == 0, 'a limited device must not block other devices'
    assert kernel.read() == totals, 'other device traffic must not count against this allowance'

    records[key].update(down=totals[usage.counter_name(key, 'down')],
                        up=totals[usage.counter_name(key, 'up')], limit=2000)
    kernel.install(devices, records, kernel.read())
    assert ping(1).returncode == 0, 'increasing allowance should restore access'
    records[key].update(down=0, up=0, limit=800)
    kernel.install(devices, records, kernel.read(), reset=True)
    assert sum(kernel.read().values()) == 0
    assert ping(1).returncode == 0, 'new day should restore access'
    print('PASS: real upload/download counting, combined quota blocking, allowance increase and daily reset.')
finally:
    for process in (pc, wan):
        process.terminate()
        process.wait()
