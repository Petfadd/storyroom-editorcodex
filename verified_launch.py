"""Start the verified Storyroom build on its own local port.

Before starting, it checks every required Python library and installs any that are
missing into Storyroom's own environment, so an update that adds a library, or a
library that went missing, never breaks the editor with server errors.
"""
from __future__ import annotations
import os, pathlib, socket, subprocess, sys, time, urllib.request, json, webbrowser

BASE=pathlib.Path(__file__).resolve().parent
PORT=int(os.environ.get('STORYROOM_VERIFIED_PORT','8004'))
EXPECTED_BUILD='2026-11-26-cinematic-graphics-review-v31'
URL=f'http://127.0.0.1:{PORT}'

def port_is_busy():
    try:
        with socket.create_connection(('127.0.0.1',PORT),timeout=0.5):
            return True
    except OSError:
        return False

def main():
    if not (BASE/'app.py').is_file() or not (BASE/'templates'/'index.html').is_file():
        print('ERROR: Expected app.py and templates/index.html beside this launcher.')
        return 2
    if port_is_busy():
        print(f'ERROR: Port {PORT} is already being used. Close that server or choose a free port.')
        print('The launcher will NOT open another application by mistake.')
        return 2
    try:
        sys.path.insert(0,str(BASE))
        import dependencies
        print('Checking required libraries...',flush=True)
        still=dependencies.ensure(BASE)
        if still:
            print('WARNING: Storyroom will start, but some features will not work until the')
            print('missing libraries install. Use "Repair now" in the editor or restart later.')
    except Exception as err:  # never block the editor on the check itself
        print('Library check skipped:',err)
    env=os.environ.copy()
    env['PORT']=str(PORT)
    env['STORYROOM_HOST']='127.0.0.1'
    print('STORYROOM VERIFIED BUILD:', EXPECTED_BUILD)
    print('APPLICATION SOURCE:', BASE)
    print('NEW URL:',URL)
    print('Launching...',flush=True)
    child=subprocess.Popen([sys.executable,'-u','app.py'],cwd=BASE,env=env)
    try:
        for _ in range(120):
            if child.poll() is not None:
                print('ERROR: Storyroom exited during startup. Read the error above.')
                return child.returncode or 1
            try:
                with urllib.request.urlopen(URL+'/api/build-info',timeout=0.5) as response:
                    data=json.load(response)
                if data.get('build')!=EXPECTED_BUILD:
                    print('ERROR: Wrong Storyroom build is responding on this port.')
                    return 3
                print('VERIFIED: Updated editor is now running.')
                print('Open this exact address:',URL+'/?build='+EXPECTED_BUILD)
                webbrowser.open(URL+'/?build='+EXPECTED_BUILD)
                break
            except (OSError,ValueError):
                time.sleep(0.25)
        else:
            print('ERROR: Editor did not become ready. Check messages above.')
            return 3
        return child.wait()
    except KeyboardInterrupt:
        print('Stopping updated Storyroom...')
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill()

if __name__=='__main__':
    raise SystemExit(main())
