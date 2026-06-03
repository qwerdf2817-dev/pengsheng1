"""
启动 Flask + 公网隧道，生成可分享到微信群的链接。

用法：
  python share.py

首次使用需要生成 SSH 密钥（只需一次）：
  ssh-keygen -t rsa -f %USERPROFILE%/.ssh/id_rsa_localhost -N ""

隧道服务：localhost.run（免费，无需注册）
"""

import sys
import subprocess
import threading
import re
import time
import os
from app import create_app

PORT = 5000

# SSH key path
SSH_KEY = os.path.join(os.path.expanduser('~'), '.ssh', 'id_rsa_localhost')


def ensure_ssh_key():
    """Generate SSH key if not exists."""
    if not os.path.exists(SSH_KEY):
        print('首次使用，正在生成 SSH 密钥...')
        ssh_dir = os.path.dirname(SSH_KEY)
        os.makedirs(ssh_dir, exist_ok=True)
        subprocess.run(
            ['ssh-keygen', '-t', 'rsa', '-f', SSH_KEY, '-N', '', '-q'],
            check=False,
        )
        print('密钥已生成\n')


def start_flask():
    app = create_app()
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)


def run_tunnel():
    """Start localhost.run tunnel."""
    ensure_ssh_key()

    cmd = [
        'ssh', '-o', 'StrictHostKeyChecking=accept-new',
        '-o', 'UserKnownHostsFile=NUL',
        '-o', 'ServerAliveInterval=60',
        '-i', SSH_KEY,
        '-R', f'80:localhost:{PORT}',
        'localhost.run',
    ]

    print('正在建立公网隧道（localhost.run）...\n')

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    url_found = None
    for line in proc.stdout:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Look for lhr.life URL
        match = re.search(r'https://[\w-]+\.lhr\.life', line_stripped)
        if match and not url_found:
            url_found = match.group(0)
            print('\n' + '=' * 56)
            print(f'  公网地址（复制发到微信群）:')
            print(f'  {url_found}')
            print('=' * 56)
            print()
            print('其他人打开这个链接就能注册/登录并编辑表格。')
            print('按 Ctrl+C 停止服务\n')

    proc.wait()


def main():
    # Start Flask in background
    t = threading.Thread(target=start_flask, daemon=True)
    t.start()
    time.sleep(2)

    print(f'Flask 已启动: http://localhost:{PORT}\n')

    try:
        run_tunnel()
    except KeyboardInterrupt:
        print('\n已停止')


if __name__ == '__main__':
    main()
