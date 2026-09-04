import os

bridge_dir = "/apollo/carla_apollo_bridge/carla_cyber_bridge"

replacements = {
    "from cyber_py import cyber, cyber_time , cyber_timer": "from cyber.python.cyber_py3 import cyber, cyber_time, cyber_timer",
    "from cyber_py import cyber, cyber_time, cyber_timer": "from cyber.python.cyber_py3 import cyber, cyber_time, cyber_timer",
    "from cyber_py import": "from cyber.python.cyber_py3 import",
    "modules.localization.proto.localization_pb2": "modules.common_msgs.localization_msgs.localization_pb2",
    "modules.canbus.proto.chassis_pb2": "modules.common_msgs.chassis_msgs.chassis_pb2",
    "modules.control.proto.control_cmd_pb2": "modules.common_msgs.control_msgs.control_cmd_pb2",
    "modules.transform.proto.transform_pb2": "modules.common_msgs.transform_msgs.transform_pb2",
    "modules.drivers.proto.pointcloud_pb2": "modules.common_msgs.sensor_msgs.pointcloud_pb2",
    "modules.localization.proto.imu_pb2": "modules.common_msgs.localization_msgs.imu_pb2",
    "modules.drivers.gnss.proto.imu_pb2": "modules.common_msgs.sensor_msgs.imu_pb2",
    "modules.localization.proto.gps_pb2": "modules.common_msgs.localization_msgs.gps_pb2",
    "modules.perception.proto.perception_obstacle_pb2": "modules.common_msgs.perception_msgs.perception_obstacle_pb2",
    "modules.perception.proto.traffic_light_detection_pb2": "modules.common_msgs.perception_msgs.traffic_light_detection_pb2",
    "modules.drivers.proto.sensor_image_pb2": "modules.common_msgs.sensor_msgs.sensor_image_pb2",
    "modules.common.proto.geometry_pb2": "modules.common_msgs.basic_msgs.geometry_pb2",
    "modules.drivers.gnss.proto.gnss_best_pose_pb2": "modules.common_msgs.sensor_msgs.gnss_best_pose_pb2",
    "modules.drivers.gnss.proto.gnss_status_pb2": "modules.common_msgs.sensor_msgs.gnss_status_pb2",
    "modules.drivers.gnss.proto.heading_pb2": "modules.common_msgs.sensor_msgs.heading_pb2",
    "modules.drivers.gnss.proto.ins_pb2": "modules.common_msgs.sensor_msgs.ins_pb2",
    "modules.localization.proto.pose_pb2": "modules.common_msgs.localization_msgs.pose_pb2"
}

for root, _, files in os.walk(bridge_dir):
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            with open(path, "r") as fp:
                content = fp.read()
            
            modified = False
            for k, v in replacements.items():
                if k in content:
                    content = content.replace(k, v)
                    modified = True
            
            if modified:
                with open(path, "w") as fp:
                    fp.write(content)
                print(f"Patched {f}")
