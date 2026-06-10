"""Upload SSH key to Aliyun server, then install & run the project."""
import subprocess
import os
import time

SERVER = '47.96.137.94'
PASSWORD = 'Aa123456'
SSH_OPTS = ['-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=/dev/null']

def run_ssh_password(cmd):
    """Run a command via SSH with password authentication."""
    full_cmd = ['ssh'] + SSH_OPTS + ['-T', f'root@{SERVER}'] + [cmd]
    proc = subprocess.Popen(
        full_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = proc.communicate(input=PASSWORD + '\n', timeout=30)
    return stdout, stderr, proc.returncode

def run_ssh(cmd):
    """Run command via SSH (assumes key-based auth is set up)."""
    # Try with key first
    key_path = os.path.expanduser('~/.ssh/id_rsa')
    result = subprocess.run(
        ['ssh'] + SSH_OPTS + ['-i', key_path, '-T', f'root@{SERVER}', cmd],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout, result.stderr, result.returncode

# Step 1: Upload SSH public key
print('=== Step 1: Uploading SSH key ===')
pubkey_path = os.path.expanduser('~/.ssh/id_rsa.pub')
if not os.path.exists(pubkey_path):
    print('No SSH key found, generating one...')
    subprocess.run(['ssh-keygen', '-t', 'rsa', '-f', os.path.expanduser('~/.ssh/id_rsa'), '-N', '', '-q'], check=False)

pubkey = open(pubkey_path).read().strip()
cmd = f'mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo "{pubkey}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo "KEY_OK"'
stdout, stderr, rc = run_ssh_password(cmd)
print(stdout)
if stderr:
    print('stderr:', stderr[:500])
if 'KEY_OK' not in stdout:
    print('Key upload may have failed, trying alternate method...')
    # Try simpler approach
    stdout, stderr, rc = run_ssh_password(f'echo "{pubkey}" > /tmp/key && mkdir -p ~/.ssh && cat /tmp/key >> ~/.ssh/authorized_keys && echo OK')
    print(stdout)

# Step 2: Test key connection
print('\n=== Step 2: Testing key-based connection ===')
stdout, stderr, rc = run_ssh('echo "KEY_AUTH_OK" && python3 --version && whoami')
print(stdout)
if 'KEY_AUTH_OK' not in stdout:
    print('Key authentication failed! Trying password again...')
    stdout, stderr, rc = run_ssh_password('python3 --version')
    print(stdout)

# Step 3: Install packages
print('\n=== Step 3: Installing Python packages ===')
stdout, stderr, rc = run_ssh('apt update -qq && apt install python3-pip -y -qq 2>&1 | tail -3')
print(stdout)

# Step 4: Upload project
print('\n=== Step 4: Upload project files ===')
project_dir = r'D:\claude projects\pengsheng'
# Use scp with key
key_path = os.path.expanduser('~/.ssh/id_rsa')
scp_cmd = [
    'scp'] + SSH_OPTS + ['-i', key_path, '-r',
    '-q',
    f'{project_dir}/app',
    f'{project_dir}/utils',
    f'{project_dir}/migrations',
    f'{project_dir}/requirements.txt',
    f'{project_dir}/run.py',
    f'{project_dir}/.env',
    f'root@{SERVER}:/root/pengsheng/'
]
print('Uploading files...')
result = subprocess.run(['ssh'] + SSH_OPTS + ['-i', key_path, '-T', f'root@{SERVER}', 'mkdir -p /root/pengsheng'], capture_output=True, text=True)
result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=60)
if result.returncode != 0:
    print('scp failed:', result.stderr[:500])

# Step 5: Install requirements
print('\n=== Step 5: pip install ===')
stdout, stderr, rc = run_ssh('cd /root/pengsheng && pip3 install -r requirements.txt -q 2>&1 | tail -5')
print(stdout)
if stderr:
    print('pip stderr:', stderr[:500])

# Step 6: Init database
print('\n=== Step 6: Initialize database ===')
stdout, stderr, rc = run_ssh('cd /root/pengsheng && FLASK_APP=run.py flask create-admin 2>&1')
print(stdout)

# Step 7: Start Flask with nohup
print('\n=== Step 7: Starting Flask ===')
stdout, stderr, rc = run_ssh('cd /root/pengsheng && nohup python3 run.py > app.log 2>&1 & sleep 2 && echo "FLASK_STARTED"')
print(stdout)

# Step 8: Verify
print('\n=== Step 8: Verify server is running ===')
stdout, stderr, rc = run_ssh('curl -s -o /dev/null -w "%{http_code}" http://localhost:5000')
print(f'Local HTTP status: {stdout}')

print('\n=== DONE ===')
print(f'Your app should be available at: http://{SERVER}')
