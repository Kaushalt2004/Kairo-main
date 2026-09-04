import sys
import os

file_path = "/mnt/c/Users/project/KAIRO/apollo/carla_apollo_bridge/carla_cyber_bridge/run_bridge.py"
with open(file_path, "r") as f:
    content = f.read()

new_content = "import sys\nsys.path.append('/apollo')\n" + content

with open(file_path, "w") as f:
    f.write(new_content)
