import sys
import time

try:
    from cyber.python.cyber_py3 import cyber
    from modules.routing.proto.routing_pb2 import RoutingRequest, LaneWaypoint
    from modules.planning.proto.pad_msg_pb2 import PadMessage, DrivingAction
except ImportError as e:
    print(f"Error importing Apollo Cyber modules: {e}")
    sys.exit(1)

def main():
    cyber.init()
    node = cyber.Node("auto_drive_node")

    routing_writer = node.create_writer('/apollo/routing_request', RoutingRequest)
    pad_writer = node.create_writer('/apollo/planning/pad', PadMessage)
    
    print("Sending Routing Request...")
    # Wait for writers to be ready
    time.sleep(2)

    # Create Routing Request
    # From CARLA Town03 spawn point to somewhere ahead
    req = RoutingRequest()
    req.header.timestamp_sec = cyber.Time.now().to_sec()
    req.header.module_name = 'routing'
    
    wp1 = req.waypoint.add()
    wp1.pose.x = 244.0
    wp1.pose.y = -65.0
    
    wp2 = req.waypoint.add()
    wp2.pose.x = 200.0
    wp2.pose.y = -65.0
    
    routing_writer.write(req)
    print("Routing Request sent!")
    
    print("Waiting 3 seconds for routing to calculate...")
    time.sleep(3)
    
    print("Sending START command to Planning...")
    pad_msg = PadMessage()
    pad_msg.action = DrivingAction.START
    pad_writer.write(pad_msg)
    print("START command sent!")
    
    cyber.shutdown()

if __name__ == '__main__':
    main()
