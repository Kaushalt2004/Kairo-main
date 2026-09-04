import sys
sys.path.append("/apollo/cyber/python/internal")
try:
    from cyber_py import cyber
    print("cyber_py worked")
except ImportError as e:
    print("cyber_py error:", e)

try:
    from cyber_py3 import cyber
    print("cyber_py3 worked")
except ImportError as e:
    print("cyber_py3 error:", e)

try:
    from cyber.python.cyber_py3 import cyber
    print("cyber.python.cyber_py3 worked")
except ImportError as e:
    print("cyber.python.cyber_py3 error:", e)
