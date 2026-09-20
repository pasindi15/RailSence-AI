import os
import sys
import psutil

TARGET_PORTS = {3000, 8001, 8002, 8003, 8004, 8005, 8006}
my_pid = os.getpid()

def kill_proc_tree(p):
    try:
        children = p.children(recursive=True)
        for child in children:
            if child.pid != my_pid:
                try:
                    child.kill()
                except Exception:
                    pass
        p.kill()
    except Exception:
        pass

# 1. Kill any python process with spawn_main or uvicorn or serve.py
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.pid == my_pid:
            continue
        pname = proc.info['name'] or ''
        cmdline = ' '.join(proc.info['cmdline'] or []).lower()
        if 'python' in pname.lower():
            if any(k in cmdline for k in ['spawn_main', 'uvicorn', 'serve.py']):
                kill_proc_tree(proc)
        elif 'powershell' in pname.lower():
            if any(k in cmdline for k in ['main:app', 'serve.py', 'start_all.ps1']):
                kill_proc_tree(proc)
    except Exception:
        pass

# 2. Check all TCP listeners on target ports
for conn in psutil.net_connections(kind='tcp'):
    try:
        if conn.laddr and conn.laddr.port in TARGET_PORTS:
            pid = conn.pid
            if pid and pid != my_pid and pid > 4:
                try:
                    p = psutil.Process(pid)
                    kill_proc_tree(p)
                except Exception:
                    pass
    except Exception:
        pass

print("Port cleanup complete.")
