#!/usr/bin/env python3
"""macOS bootstrap for the real-dump UI audit; fail closed before app import."""
import argparse
import ctypes
import errno
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
PROFILE = HERE / 'fence.sb'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--dump', type=Path)
    p.add_argument('--report', type=Path)
    p.add_argument('--evidence-dir', type=Path)
    p.add_argument('--forms-only', action='store_true')
    p.add_argument('--screens-only', action='store_true')
    p.add_argument('--synthetic-runtime', action='store_true')
    p.add_argument('--registry', type=Path)
    p.add_argument('--mutation-test', action='store_true')
    p.add_argument('--capture-out', type=Path)
    p.add_argument('--login-only', action='store_true')
    args = p.parse_args()
    if sys.platform != 'darwin':
        p.error('the UI audit requires macOS sandbox-exec; use the macOS CI runner')
    probe = r'''import ctypes, errno, os, socket, subprocess
f=ctypes.CDLL('/usr/lib/libSystem.B.dylib').sandbox_check
f.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int]; f.restype=ctypes.c_int
if f(os.getpid(),b'network-outbound',0)!=1: raise SystemExit('OS fence missing')
for host,port in [('192.0.2.1',18881),('127.0.0.1',18884)]:
    if socket.socket().connect_ex((host,port))!=errno.EPERM: raise SystemExit('fence negative probe failed')
child=subprocess.run(['/usr/bin/ruby','-rsocket','-e',
    'begin; TCPSocket.new("192.0.2.1",18881); rescue SystemCallError => e; puts e.errno; end'],
    capture_output=True,text=True)
if child.returncode or child.stdout.strip()!=str(errno.EPERM): raise SystemExit('native child fence failed')
print('OS_FENCE_NEGATIVE_PASS external_same_port=EPERM other_local_port=EPERM native_child=EPERM')'''
    prefix = ['/usr/bin/sandbox-exec', '-f', str(PROFILE)]
    clean_env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'TMPDIR') if k in os.environ}
    clean_env['PYTHON_DOTENV_DISABLED'] = '1'
    tested = subprocess.run(prefix + [sys.executable, '-c', probe], check=False, env=clean_env)
    if tested.returncode:
        raise SystemExit('OS fence negative probe failed; app import refused')
    if args.synthetic_runtime:
        command = prefix + [sys.executable, str(HERE / 'synthetic_runtime.py'),
                            '--baseline', str(args.baseline), '--candidate', str(args.candidate)]
        if args.registry:
            command += ['--registry', str(args.registry)]
        if args.mutation_test:
            command.append('--mutation-test')
        if args.capture_out:
            command += ['--capture-out', str(args.capture_out)]
        if args.login_only:
            command.append('--login-only')
        if args.evidence_dir:
            command += ['--evidence-dir', str(args.evidence_dir)]
    else:
        if not args.dump or not args.report or not args.evidence_dir:
            p.error('--dump, --report and --evidence-dir required for raw-dump audit')
        command = prefix + [sys.executable, str(HERE / 'ui_audit.py'),
                            '--baseline', str(args.baseline), '--candidate', str(args.candidate),
                            '--dump', str(args.dump), '--report', str(args.report),
                            '--evidence-dir', str(args.evidence_dir)]
        if args.forms_only:
            command.append('--forms-only')
        if args.screens_only:
            command.append('--screens-only')
    return subprocess.run(command, check=False, env=clean_env).returncode


if __name__ == '__main__':
    sys.exit(main())
