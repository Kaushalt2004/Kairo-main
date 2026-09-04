import sys
import time

sys.path.append('/apollo')
sys.path.append('/apollo/bazel-bin/cyber/python/internal')
sys.path.append('/apollo/bazel-bin')

from cyber.python.cyber_py3 import cyber
from modules.localization.proto.localization_pb2 import LocalizationEstimate
from modules.routing.proto.routing_pb2 import RoutingRequest
from modules.planning.proto.pad_msg_pb2 import PadMessage, DrivingAction

def main():
    cyber.init()
    node = cyber.Node('kairo_route_starter')

    current_pos = None
    current_heading = 0.0

    def loc_cb(msg):
        nonlocal current_pos, current_heading
        current_pos = msg.pose.position
        current_heading = msg.pose.heading

    reader = node.create_reader('/apollo/localization/pose', LocalizationEstimate, loc_cb)
    
    # Wait for localization message
    for _ in range(30):
        if current_pos is not None:
            break
        time.sleep(0.1)

    if current_pos is None:
        print("ERROR: No localization pose received on /apollo/localization/pose")
        cyber.shutdown()
        return

    print(f"Current car location: X={current_pos.x:.2f}, Y={current_pos.y:.2f}, Z={current_pos.z:.2f}")

    # Create routing writers
    routing_writer = node.create_writer('/apollo/routing_request', RoutingRequest)
    pad_writer = node.create_writer('/apollo/planning/pad', PadMessage)
    pad_ctrl_writer = node.create_writer('/apollo/control/pad', PadMessage)
    time.sleep(1)

    import math
    # Calculate destination 60 meters ahead in the heading direction
    dx = 60.0 * math.cos(current_heading)
    dy = 60.0 * math.sin(current_heading)

    req = RoutingRequest()
    req.header.timestamp_sec = cyber.Time.now().to_sec()
    req.header.module_name = 'routing'

    wp1 = req.waypoint.add()
    wp1.pose.x = current_pos.x
    wp1.pose.y = current_pos.y

    wp2 = req.waypoint.add()
    wp2.pose.x = current_pos.x + dx
    wp2.pose.y = current_pos.y + dy

    routing_writer.write(req)
    print(f"Routing request sent from ({wp1.pose.x:.2f}, {wp1.pose.y:.2f}) to ({wp2.pose.x:.2f}, {wp2.pose.y:.2f})!")

    print("Waiting 2 seconds for planning to calculate trajectory...")
    time.sleep(2)

    pad_msg = PadMessage()
    pad_msg.action = DrivingAction.START
    pad_writer.write(pad_msg)
    pad_ctrl_writer.write(pad_msg)
    print("START command published to /apollo/planning/pad and /apollo/control/pad!")

    cyber.shutdown()

if __name__ == '__main__':
    main()
