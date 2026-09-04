from cyber.python.cyber_py3 import cyber
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
import time

def callback(data):
    print(f"Pose: x={data.pose.position.x}, y={data.pose.position.y}")

def main():
    cyber.init()
    node = cyber.Node("test_loc_node")
    node.create_reader("/apollo/localization/pose", LocalizationEstimate, callback)
    print("Listening to /apollo/localization/pose for 3 seconds...")
    time.sleep(3)
    cyber.shutdown()

if __name__ == '__main__':
    main()
