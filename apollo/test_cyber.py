from cyber.python.cyber_py3 import cyber
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand
import time

def callback(data):
    print(f"Throttle: {data.throttle}, Brake: {data.brake}, Steering: {data.steering_target}")

def main():
    cyber.init()
    node = cyber.Node("test_control_node")
    node.create_reader("/apollo/control", ControlCommand, callback)
    print("Listening to /apollo/control for 3 seconds...")
    time.sleep(3)
    cyber.shutdown()

if __name__ == '__main__':
    main()
