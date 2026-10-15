#! python3
# Rhino Mind Canvas command: MCFloor
import os, sys
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
import mindcanvas.boot
mindcanvas.boot.run("floor")
