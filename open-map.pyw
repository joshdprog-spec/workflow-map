"""Open Workflow Map like an app: make sure the local server is up, then open the map in a chromeless browser window.

Run by the desktop / Start Menu shortcut (pythonw, so no console). Falls back to the HTML file if the server will not start.
"""
import json, os, socket, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config.json", encoding="utf-8")) if (HERE / "config.json").exists() else {}
PORT = int(CFG.get("search_port", 27183))
URL = f"http://127.0.0.1:{PORT}/map"
PAGE = Path(CFG.get("output_html", HERE / "00-WORKFLOW-MAP.html"))


def up():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.4):
            return True
    except OSError:
        return False


def start_server():
    script = HERE / "search-server.py"
    if not script.exists():
        return
    py = Path(sys.executable)
    py = py.with_name("python.exe") if py.name.lower() == "pythonw.exe" else py
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    subprocess.Popen([str(py), str(script), "--port", str(PORT)], **kw)


def browser():
    cands = [CFG.get("browser_path", "")]
    if sys.platform == "win32":
        pf, pf86, local = os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")
        cands += [os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"), os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"), os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    else:
        cands += ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/microsoft-edge"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def main():
    if not up():
        start_server()
        for _ in range(20):
            time.sleep(0.2)
            if up():
                break
    target = URL + "#home" if up() else PAGE.as_uri() + "#home"
    b = browser()
    if b:
        subprocess.Popen([b, f"--app={target}", "--window-size=1400,900", "--window-name=Workflow Map"], close_fds=True)
    else:
        import webbrowser
        webbrowser.open(target)


if __name__ == "__main__":
    main()
