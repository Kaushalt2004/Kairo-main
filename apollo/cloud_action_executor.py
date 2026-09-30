#!/usr/bin/env python3
"""
Apollo Cloud Action Executor
Receives cloud actions (START, RESET, STOP, ROUTE) and executes them on Apollo Cyber RT topics:
- /apollo/planning/pad
- /apollo/control/pad
- /apollo/routing_request
"""

import argparse
import json
import math
import sys
import time

sys.path.insert(0, '/usr/local/lib/dreamview/dreamview.runfiles/apollo')
sys.path.append('/apollo')
sys.path.append('/apollo/bazel-bin/cyber/python/internal')
sys.path.append('/apollo/bazel-bin')

try:
    from cyber.python.cyber_py3 import cyber
    from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
    from modules.common_msgs.routing_msgs.routing_pb2 import RoutingRequest
    from modules.common_msgs.planning_msgs.pad_msg_pb2 import PadMessage as PlanningPadMessage
    from modules.common_msgs.control_msgs.pad_msg_pb2 import PadMessage as ControlPadMessage, DrivingAction as ControlDrivingAction
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Cyber import error: {e}"}))
    sys.exit(1)


def execute_action(action: str, distance: float = 60.0, dest_x: float = None, dest_y: float = None):
    cyber.init()
    node = cyber.Node(f"kairo_cloud_action_{int(time.time())}")

    plan_pad_writer = node.create_writer('/apollo/planning/pad', PlanningPadMessage)
    ctrl_pad_writer = node.create_writer('/apollo/control/pad', ControlPadMessage)
    routing_writer = node.create_writer('/apollo/routing_request', RoutingRequest)

    time.sleep(0.5)
    action_upper = action.upper()
    result = {"status": "success", "action": action_upper}

    if action_upper in ("START", "AUTONOMOUS", "FOLLOW", "START_SIMULATION", "ENGAGE_AUTONOMOUS"):
        # 1. Check localization to send routing request if needed
        current_pos = None
        current_heading = 0.0

        def loc_cb(msg):
            nonlocal current_pos, current_heading
            current_pos = msg.pose.position
            current_heading = msg.pose.heading

        loc_reader = node.create_reader('/apollo/localization/pose', LocalizationEstimate, loc_cb)
        for _ in range(15):
            if current_pos is not None:
                break
            time.sleep(0.1)

        if current_pos is not None:
            # Send routing request ahead
            req = RoutingRequest()
            req.header.timestamp_sec = time.time()
            req.header.module_name = 'kairo_cloud_action'

            wp1 = req.waypoint.add()
            wp1.pose.x = current_pos.x
            wp1.pose.y = current_pos.y

            wp2 = req.waypoint.add()
            if dest_x is not None and dest_y is not None:
                wp2.pose.x = dest_x
                wp2.pose.y = dest_y
            else:
                wp2.pose.x = current_pos.x + distance * math.cos(current_heading)
                wp2.pose.y = current_pos.y + distance * math.sin(current_heading)

            routing_writer.write(req)
            result["routing"] = {
                "start": {"x": wp1.pose.x, "y": wp1.pose.y},
                "target": {"x": wp2.pose.x, "y": wp2.pose.y}
            }
            time.sleep(1.0)

        # 2. Publish Planning FOLLOW command
        plan_pad = PlanningPadMessage()
        plan_pad.action = PlanningPadMessage.FOLLOW
        plan_pad_writer.write(plan_pad)

        # 3. Publish Control START command
        ctrl_pad = ControlPadMessage()
        ctrl_pad.action = ControlDrivingAction.START
        ctrl_pad_writer.write(ctrl_pad)

        result["apollo_mode"] = "AUTONOMOUS"
        result["message"] = "Autonomous driving engaged in Apollo (FOLLOW + START)"

    elif action_upper in ("RESET", "MANUAL", "STOP_SIMULATION", "DISENGAGE_AUTONOMOUS"):
        # Publish Planning CLEAR_PLANNING and Control RESET
        plan_pad = PlanningPadMessage()
        plan_pad.action = PlanningPadMessage.CLEAR_PLANNING
        plan_pad_writer.write(plan_pad)

        ctrl_pad = ControlPadMessage()
        ctrl_pad.action = ControlDrivingAction.RESET
        ctrl_pad_writer.write(ctrl_pad)

        result["apollo_mode"] = "MANUAL"
        result["message"] = "Autonomous driving disengaged (CLEAR_PLANNING + RESET)"

    elif action_upper in ("STOP", "EMERGENCY_STOP", "E_STOP"):
        # Publish Planning STOP
        plan_pad = PlanningPadMessage()
        plan_pad.action = PlanningPadMessage.STOP
        plan_pad_writer.write(plan_pad)

        ctrl_pad = ControlPadMessage()
        ctrl_pad.action = ControlDrivingAction.RESET
        ctrl_pad_writer.write(ctrl_pad)

        result["apollo_mode"] = "EMERGENCY_STOP"
        result["message"] = "Emergency stop dispatched to Apollo (/apollo/planning/pad STOP)"

    elif action_upper == "ROUTE":
        current_pos = None
        current_heading = 0.0

        def loc_cb(msg):
            nonlocal current_pos, current_heading
            current_pos = msg.pose.position
            current_heading = msg.pose.heading

        loc_reader = node.create_reader('/apollo/localization/pose', LocalizationEstimate, loc_cb)
        for _ in range(20):
            if current_pos is not None:
                break
            time.sleep(0.1)

        if current_pos is None:
            result["status"] = "error"
            result["message"] = "No localization pose received from /apollo/localization/pose"
        else:
            req = RoutingRequest()
            req.header.timestamp_sec = time.time()
            req.header.module_name = 'kairo_cloud_action'

            wp1 = req.waypoint.add()
            wp1.pose.x = current_pos.x
            wp1.pose.y = current_pos.y

            wp2 = req.waypoint.add()
            if dest_x is not None and dest_y is not None:
                wp2.pose.x = dest_x
                wp2.pose.y = dest_y
            else:
                wp2.pose.x = current_pos.x + distance * math.cos(current_heading)
                wp2.pose.y = current_pos.y + distance * math.sin(current_heading)

            routing_writer.write(req)
            result["routing"] = {
                "start": {"x": wp1.pose.x, "y": wp1.pose.y},
                "target": {"x": wp2.pose.x, "y": wp2.pose.y}
            }

            time.sleep(1.0)
            plan_pad = PlanningPadMessage()
            plan_pad.action = PlanningPadMessage.FOLLOW
            plan_pad_writer.write(plan_pad)
            result["message"] = "Route dispatched and FOLLOW commanded"
    else:
        result["status"] = "ignored"
        result["message"] = f"Unknown action: {action}"

    time.sleep(0.5)
    cyber.shutdown()
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description="Apollo Cloud Action Dispatcher")
    parser.add_argument("--action", required=True, help="START, RESET, STOP, ROUTE, AUTONOMOUS, MANUAL, EMERGENCY_STOP")
    parser.add_argument("--distance", type=float, default=60.0, help="Forward distance in meters for routing")
    parser.add_argument("--x", type=float, default=None, help="Target destination X")
    parser.add_argument("--y", type=float, default=None, help="Target destination Y")
    args = parser.parse_args()

    execute_action(
        action=args.action,
        distance=args.distance,
        dest_x=args.x,
        dest_y=args.y
    )


if __name__ == '__main__':
    main()
