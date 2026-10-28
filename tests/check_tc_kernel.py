"""Run: unshare -Urn python3 -m tests.check_tc_kernel (no host changes)."""
import json
import subprocess

import commands
import tollbooth


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def check():
    run('ip', 'link', 'add', 'test0', 'type', 'dummy')
    run('ip', 'link', 'add', 'ifbtest', 'type', 'ifb')
    tollbooth.init_meters('test0', 'ifbtest')
    for command in commands.tc_limit_cmds('test0', '10.42.0.101', 400, 80, 'ifbtest'):
        run(*command)
    tollbooth.init_meters('test0', 'ifbtest')
    for interface in ('test0', 'ifbtest'):
        classes = json.loads(run('tc', '-j', 'class', 'show', 'dev', interface))
        assert any(item['handle'] == '1:201' for item in classes), classes
    print('PASS: repeated meter initialization succeeds and preserves device caps.')


if __name__ == '__main__':
    check()
