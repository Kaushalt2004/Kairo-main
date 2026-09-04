#!/usr/bin/env python3
import sys
sys.path.append('/apollo')
from cyber.python.cyber_py3 import cyber
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
import time

def planning_callback(data):
    print("Received Planning Msg! Points:", len(data.trajectory_point))

def control_callback(data):
    print("Received Control Msg! Throttle:", data.throttle, "Brake:", data.brake, "Steer:", data.steering_target)

cyber.init()
node = cyber.Node("debug_node")
node.create_reader('/apollo/planning', ADCTrajectory, planning_callback)
node.create_reader('/apollo/control', ControlCommand, control_callback)

print("Listening for Planning and Control messages for 5 seconds...")
time.sleep(5)
cyber.shutdown()
