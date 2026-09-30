import os
import subprocess
import tempfile
import time
import pytest
import shutil

def is_docker_ready():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    except Exception:
        return False

@pytest.mark.skipif(not is_docker_ready(), reason="Docker is not running or not installed")
def test_docker_startup_with_empty_volume():
    worker_dir = os.path.join(os.path.dirname(__file__), '..', 'ChannelsWorker')
    
    # Build image
    res = subprocess.run(["docker", "build", "-t", "calccrm-smoke-test", "."], 
                         cwd=worker_dir, capture_output=True, text=True)
    assert res.returncode == 0, f"Docker build failed: {res.stderr}"

    with tempfile.TemporaryDirectory() as tmp_volume:
        # Run container
        container_id = subprocess.check_output(
            ["docker", "run", "-d", "-v", f"{tmp_volume}:/data", "calccrm-smoke-test"]
        ).decode().strip()

        try:
            time.sleep(5)
            logs = subprocess.check_output(["docker", "logs", container_id]).decode()
            
            # 1. Assert supervisor started
            assert "supervisord started" in logs.lower()
            
            # 2. Assert no fatal 'file exists' error from wa-bridge
            assert "mkdir store: file exists" not in logs.lower()
        finally:
            subprocess.run(["docker", "rm", "-f", container_id], capture_output=True)
