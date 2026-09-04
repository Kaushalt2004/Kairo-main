#!/bin/bash
source /apollo/cyber/setup.bash
export CARLA_PYTHON_ROOT=/root/carla_apollo_bridge_13/carla-python-0.9.13
export PYTHONPATH=$CARLA_PYTHON_ROOT/carla:$CARLA_PYTHON_ROOT/carla/dist/carla-0.9.13-py2.7-linux-x86_64.egg:$PYTHONPATH
cd /root/carla_apollo_bridge_13
nohup python carla_cyber_bridge/run_bridge.py > /tmp/run_bridge.log 2>&1 &
