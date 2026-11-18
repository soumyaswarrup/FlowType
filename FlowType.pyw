"""Start FlowType without a console window (no .bat needed).
Double-click this file. If install.pyw has been run, FlowType's own environment is used."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
venv = os.path.join(HERE, ".venv", "Scripts" if sys.platform == "win32" else "bin",
                    "pythonw.exe" if sys.platform == "win32" else "python")
if os.path.exists(venv) and os.path.abspath(sys.executable).lower() != os.path.abspath(venv).lower():
    subprocess.Popen([venv, os.path.join(HERE, "flowtype.py")], cwd=HERE,
                     creationflags=0x08000000 if sys.platform == "win32" else 0)
else:
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    sys.argv = [os.path.join(HERE, "flowtype.py")] + sys.argv[1:]
    import runpy
    runpy.run_path(sys.argv[0], run_name="__main__")
