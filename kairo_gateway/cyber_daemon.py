#!/usr/bin/env python3
"""
KAIRO Cyber daemon - runs INSIDE the Apollo container.

kairo_gateway starts this through a persistent `docker exec -i` pipe, so no
extra container ports are needed. Protocol is JSON lines:

  stdout  {"type": "telemetry", ...}            ~5 Hz vehicle snapshot
          {"type": "reply", "id": N, "ok": bool, "data"|"error": ...}
  stdin   {"id": N, "cmd": "<name>", ...args}

Commands:
  ping
  lane_follow   x, y, [heading], [target_speed]   route + drive to a point
  action        command = START|STOP|PULL_OVER|CLEAR_PLANNING|FOLLOW|...
  map_lanes                                       lane centerlines of the
                                                  currently loaded HD map
  signals       turn, high_beam, low_beam, horn, emergency_light
                                                  Apollo ChassisCommand
  manual_start  x, y, heading, [speed], [gear]    KAIRO virtual vehicle takes
                                                  over pose + chassis
  manual_stop                                     -> final pose
  gear          gear = P|R|N|D                    (manual only)
  drive         throttle, brake, steer            (manual only, no reply,
                                                  sent ~20 Hz by the tablet)
  traffic_start count, radius_m, [seed], [speed_factor]
                                                  simulated vehicles around the car
  traffic_stop / traffic_status
  hazard_start  hazard_id, kind = phantom_obstacle|cut_in|perception_dropout,
                params                            in-world hazards
  hazard_stop   hazard_id

Must stay compatible with the container's Python 3.6.
"""

import json
import math
import os
import sys
import threading
import time

sys.path.append('/apollo')
sys.path.append('/apollo/bazel-bin/cyber/python/internal')
sys.path.append('/apollo/bazel-bin')

from cyber.python.cyber_py3 import cyber  # noqa: E402
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis  # noqa: E402
from modules.common_msgs.dreamview_msgs.hmi_status_pb2 import (  # noqa: E402
    HMIModeOperation, HMIStatus)
from modules.common_msgs.external_command_msgs.action_command_pb2 import (  # noqa: E402
    ActionCommand, ActionCommandType)
from modules.common_msgs.basic_msgs.vehicle_signal_pb2 import (  # noqa: E402
    VehicleSignal)
from modules.common_msgs.external_command_msgs.chassis_command_pb2 import (  # noqa: E402
    ChassisCommand)
from modules.common_msgs.external_command_msgs.command_status_pb2 import (  # noqa: E402
    CommandStatus, CommandStatusRequest, CommandStatusType)
from modules.common_msgs.external_command_msgs.lane_follow_command_pb2 import (  # noqa: E402
    LaneFollowCommand)
from modules.common_msgs.localization_msgs.localization_pb2 import (  # noqa: E402
    LocalizationEstimate)
from modules.common_msgs.map_msgs.map_pb2 import Map  # noqa: E402
from modules.common_msgs.monitor_msgs.system_status_pb2 import (  # noqa: E402
    ComponentStatus)
from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (  # noqa: E402
    PerceptionObstacle, PerceptionObstacles)
from modules.common_msgs.planning_msgs.planning_command_pb2 import (  # noqa: E402
    PlanningCommand)
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory  # noqa: E402

from kairo_traffic import TrafficSim  # noqa: E402  (copied next to this file)

GLOBAL_FLAGFILE = '/apollo/modules/common/data/global_flagfile.txt'
TELEMETRY_PERIOD_S = 0.1
IDLE_PERIOD_S = 0.5
# Slow-changing fields are only re-sent when they change, or at this period
# (the gateway keeps the last copy).
RESEND_STATIC_S = 5.0
# The gateway sends a heartbeat every few seconds; without one the daemon
# assumes its gateway is gone (killed without closing the pipe) and exits,
# so restarts never leave orphaned daemons burning CPU in the container.
HEARTBEAT_TIMEOUT_S = 30.0
MAX_OBSTACLES = 60
MAX_TRAJECTORY_POINTS = 40

_out_lock = threading.Lock()
_state_lock = threading.Lock()


def emit(obj):
    line = json.dumps(obj, separators=(',', ':'))
    with _out_lock:
        sys.stdout.write(line + '\n')
        sys.stdout.flush()


def finite(value, default=None, ndigits=3):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(value) or math.isinf(value):
        return default
    return round(value, ndigits)


# --------------------------------------------------------------------------
# HD map helpers
# --------------------------------------------------------------------------

def current_map_dir():
    """Apollo appends --map_dir to the global flagfile on every map change;
    the last occurrence is the active one."""
    map_dir = None
    try:
        with open(GLOBAL_FLAGFILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith('--map_dir='):
                    map_dir = line.split('=', 1)[1]
    except IOError:
        pass
    return map_dir


def load_map(map_dir):
    hd_map = Map()
    for name in ('base_map.bin', 'base_map.txt'):
        path = os.path.join(map_dir, name)
        if not os.path.exists(path):
            continue
        if name.endswith('.bin'):
            with open(path, 'rb') as f:
                hd_map.ParseFromString(f.read())
        else:
            from google.protobuf import text_format
            with open(path) as f:
                text_format.Parse(f.read(), hd_map)
        return hd_map
    raise IOError('No base_map found in %s' % map_dir)


def lane_points(lane):
    pts = []
    for seg in lane.central_curve.segment:
        for p in seg.line_segment.point:
            pts.append((p.x, p.y))
    return pts


def simplify(points, min_step=2.0):
    """Drop points closer than min_step metres to the last kept one."""
    if len(points) <= 2:
        return points
    out = [points[0]]
    for p in points[1:-1]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) >= min_step:
            out.append(p)
    out.append(points[-1])
    return out


def slice_by_s(points, start_s, end_s):
    """Sub-polyline of `points` between arc lengths start_s and end_s."""
    if not points:
        return []
    out = []
    acc = 0.0
    prev = points[0]
    if start_s <= 0:
        out.append(prev)
    for p in points[1:]:
        seg = math.hypot(p[0] - prev[0], p[1] - prev[1])
        nxt = acc + seg
        if seg > 0:
            if acc < start_s <= nxt:
                t = (start_s - acc) / seg
                out.append((prev[0] + t * (p[0] - prev[0]),
                            prev[1] + t * (p[1] - prev[1])))
            if start_s < nxt <= end_s:
                out.append(p)
            elif acc < end_s < nxt:
                t = (end_s - acc) / seg
                out.append((prev[0] + t * (p[0] - prev[0]),
                            prev[1] + t * (p[1] - prev[1])))
                break
        acc = nxt
        prev = p
        if acc >= end_s:
            break
    return out


class MapCache(object):
    def __init__(self):
        self.map_dir = None
        self.lanes = {}  # lane id -> [(x, y), ...] full resolution
        self.lane_boxes = {}  # lane id -> (min_x, min_y, max_x, max_y)
        # Lane graph for the traffic simulation (ids of lanes kept above).
        self.successors = {}
        self.left_neighbors = {}   # same-direction lanes only
        self.right_neighbors = {}
        self.speed_limits = {}     # m/s; 0/missing on most CARLA lanes
        self.payload = None

    def ensure(self):
        map_dir = current_map_dir()
        if map_dir and map_dir != self.map_dir:
            hd_map = load_map(map_dir)
            lanes = {}
            widths = {}
            for lane in hd_map.lane:
                pts = lane_points(lane)
                if len(pts) < 2:
                    continue
                lanes[lane.id.id] = pts
                samples = [s.width for s in lane.left_sample] + \
                          [s.width for s in lane.right_sample]
                widths[lane.id.id] = (sum(samples) / len(samples) * 2) \
                    if samples else 3.5
            def kept(ids):
                return [i.id for i in ids if i.id in lanes]
            self.successors, self.left_neighbors, self.right_neighbors = {}, {}, {}
            self.speed_limits = {}
            for lane in hd_map.lane:
                lid = lane.id.id
                if lid not in lanes:
                    continue
                self.successors[lid] = kept(lane.successor_id)
                self.left_neighbors[lid] = kept(lane.left_neighbor_forward_lane_id)
                self.right_neighbors[lid] = kept(lane.right_neighbor_forward_lane_id)
                self.speed_limits[lid] = lane.speed_limit
            self.lanes = lanes
            self.lane_boxes = {
                lane_id: (min(p[0] for p in pts), min(p[1] for p in pts),
                          max(p[0] for p in pts), max(p[1] for p in pts))
                for lane_id, pts in lanes.items()
            }
            xs = [p[0] for pts in lanes.values() for p in pts]
            ys = [p[1] for pts in lanes.values() for p in pts]
            self.payload = {
                'map_dir': map_dir,
                'name': os.path.basename(map_dir.rstrip('/')),
                'bounds': {
                    'min_x': min(xs) if xs else 0, 'max_x': max(xs) if xs else 0,
                    'min_y': min(ys) if ys else 0, 'max_y': max(ys) if ys else 0,
                },
                'lanes': [
                    {
                        'id': lane_id,
                        'w': round(min(max(widths[lane_id], 2.5), 6.0), 2),
                        'pts': [[round(x, 1), round(y, 1)]
                                for x, y in simplify(pts)],
                    }
                    for lane_id, pts in lanes.items()
                ],
            }
            self.map_dir = map_dir
        return self.payload

    def snap(self, x, y, radius=25.0, heading=None):
        """Nearest point on any lane centreline within `radius` metres,
        with the lane's driving direction there. None if nothing is near.

        With `heading`, only lanes running within 90 degrees of it count
        (so a car is never put on the opposite-direction lane); falls back
        to any lane if none does."""
        if heading is not None:
            same_way = self._snap(x, y, radius, heading)
            if same_way is not None:
                return same_way
        return self._snap(x, y, radius, None)

    def _snap(self, x, y, radius, heading):
        self.ensure()
        best = None
        for lane_id, (x0, y0, x1, y1) in self.lane_boxes.items():
            if x < x0 - radius or x > x1 + radius or \
                    y < y0 - radius or y > y1 + radius:
                continue
            pts = self.lanes[lane_id]
            for i in range(len(pts) - 1):
                ax, ay = pts[i]
                bx, by = pts[i + 1]
                dx, dy = bx - ax, by - ay
                seg2 = dx * dx + dy * dy
                if seg2 == 0:
                    continue
                if heading is not None:
                    diff = math.atan2(dy, dx) - heading
                    if math.cos(diff) < 0:  # more than 90 degrees apart
                        continue
                t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg2))
                px, py = ax + t * dx, ay + t * dy
                d2 = (px - x) ** 2 + (py - y) ** 2
                if best is None or d2 < best[0]:
                    best = (d2, px, py, math.atan2(dy, dx), lane_id)
        if best is None or best[0] > radius * radius:
            return None
        d2, px, py, heading, lane_id = best
        return {'x': round(px, 2), 'y': round(py, 2),
                'heading': round(heading, 4), 'lane_id': lane_id,
                'distance': round(math.sqrt(d2), 2)}

    def route_polyline(self, routing):
        """Lane-level route (RoutingResponse) -> one polyline."""
        if not self.lanes:
            try:
                self.ensure()
            except Exception:
                return []
        line = []
        for road in routing.road:
            if not road.passage:
                continue
            # The first passage that can exit is the one the car follows.
            passage = road.passage[0]
            for p in road.passage:
                if p.can_exit:
                    passage = p
                    break
            for seg in passage.segment:
                pts = self.lanes.get(seg.id)
                if not pts:
                    continue
                line.extend(slice_by_s(pts, seg.start_s, seg.end_s))
        return [[round(x, 1), round(y, 1)] for x, y in simplify(line, 1.5)]


# --------------------------------------------------------------------------
# KAIRO virtual vehicle (manual driving)
# --------------------------------------------------------------------------

class VirtualVehicle(object):
    """Kinematic bicycle model driven by the tablet's pedals and wheel.

    Dreamview's Sim Control only does "perfect control" (it follows the
    planning trajectory and ignores throttle/steer), so manual driving can't
    go through it. While manual driving is active, Sim Control is switched
    off and this model publishes /apollo/localization/pose and
    /apollo/canbus/chassis instead, so Apollo and Dreamview see the car move
    exactly as they would a real one.
    """

    RATE_HZ = 50.0
    WHEELBASE_M = 2.85
    MAX_STEER_RAD = 0.55        # road-wheel angle at full lock
    STEER_RATE_RAD_S = 1.4
    MAX_ACCEL = 3.2             # m/s^2 at full throttle
    MAX_BRAKE = 8.0             # m/s^2 at full brake
    ROLLING = 0.25              # m/s^2 rolling resistance
    MAX_FWD_MPS = 25.0
    MAX_REV_MPS = 4.0
    DEADMAN_S = 0.8             # no input for this long -> brake (Wi-Fi jitter tolerant)

    def __init__(self, node):
        self.loc_writer = node.create_writer(
            '/apollo/localization/pose', LocalizationEstimate)
        self.chassis_writer = node.create_writer(
            '/apollo/canbus/chassis', Chassis)
        self.active = False
        self.lock = threading.Lock()
        self.x = self.y = self.heading = 0.0
        self.v = 0.0            # signed: negative when reversing
        self.accel = 0.0
        self.steer = 0.0        # road-wheel angle, + = left
        self.gear = 'P'
        self.throttle = self.brake = self.steer_cmd = 0.0
        self.last_input = 0.0
        self.signal = VehicleSignal()
        self.seq = 0
        self._thread = None

    def start(self, x, y, heading, speed=0.0, gear=None):
        with self.lock:
            self.x, self.y, self.heading = float(x), float(y), float(heading)
            self.v = max(0.0, float(speed or 0.0))
            self.gear = gear or ('D' if self.v > 0.3 else 'P')
            self.throttle = self.brake = self.steer_cmd = 0.0
            self.steer = 0.0
            self.last_input = time.time()
            if self.active:
                return
            self.active = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        with self.lock:
            self.active = False
            return {'x': self.x, 'y': self.y, 'heading': self.heading,
                    'speed': abs(self.v)}

    def set_input(self, throttle, brake, steer):
        with self.lock:
            self.throttle = min(max(float(throttle), 0.0), 1.0)
            self.brake = min(max(float(brake), 0.0), 1.0)
            self.steer_cmd = min(max(float(steer), -1.0), 1.0)
            self.last_input = time.time()

    def set_gear(self, gear):
        with self.lock:
            if gear not in ('P', 'R', 'N', 'D'):
                raise RuntimeError('Unknown gear %r' % gear)
            if gear in ('P', 'R', 'D') and gear != self.gear and abs(self.v) > 1.0:
                raise RuntimeError('Slow down below 4 km/h to shift into %s' % gear)
            self.gear = gear

    def set_signal(self, signal):
        with self.lock:
            self.signal.CopyFrom(signal)

    def snapshot(self):
        with self.lock:
            return {
                'active': self.active,
                'gear': self.gear,
                'throttle': round(self.throttle, 2),
                'brake': round(self.brake, 2),
                'steer': round(self.steer_cmd, 2),
                'deadman': self.active and
                time.time() - self.last_input > self.DEADMAN_S,
            }

    def _step(self, dt):
        if time.time() - self.last_input > self.DEADMAN_S:
            # Tablet went quiet (dropped connection, app closed): stop.
            throttle, brake, steer_cmd = 0.0, 0.6, 0.0
        else:
            throttle, brake, steer_cmd = self.throttle, self.brake, self.steer_cmd

        target = steer_cmd * self.MAX_STEER_RAD
        step = self.STEER_RATE_RAD_S * dt
        self.steer += max(-step, min(step, target - self.steer))

        if self.gear == 'P':
            throttle, brake = 0.0, 1.0
        direction = {'D': 1.0, 'R': -1.0}.get(self.gear, 0.0)
        drive = throttle * self.MAX_ACCEL * direction
        resist = brake * self.MAX_BRAKE + self.ROLLING

        v0 = self.v
        if abs(v0) < 1e-3:
            v = (drive - math.copysign(resist, drive)) * dt \
                if abs(drive) > resist else 0.0
        else:
            v = v0 + drive * dt - math.copysign(resist * dt, v0)
            if v * v0 < 0 and abs(drive) <= resist:
                v = 0.0  # resistance stops the car; it never reverses it
        v = max(-self.MAX_REV_MPS, min(self.MAX_FWD_MPS, v))
        self.accel = (v - v0) / dt
        self.v = v

        yaw_rate = v / self.WHEELBASE_M * math.tan(self.steer)
        h = self.heading + yaw_rate * dt
        self.heading = math.atan2(math.sin(h), math.cos(h))
        self.x += v * math.cos(self.heading) * dt
        self.y += v * math.sin(self.heading) * dt
        return yaw_rate

    def _publish(self, yaw_rate):
        now = time.time()
        self.seq += 1
        cos_h, sin_h = math.cos(self.heading), math.sin(self.heading)

        loc = LocalizationEstimate()
        loc.header.timestamp_sec = now
        loc.header.module_name = 'kairo_virtual_vehicle'
        loc.header.sequence_num = self.seq
        loc.measurement_time = now
        pose = loc.pose
        pose.position.x, pose.position.y, pose.position.z = self.x, self.y, 0.0
        # Apollo's vehicle frame is right-forward-up: yaw = heading - pi/2.
        yaw = self.heading - math.pi / 2
        pose.orientation.qw = math.cos(yaw / 2)
        pose.orientation.qz = math.sin(yaw / 2)
        pose.orientation.qx = pose.orientation.qy = 0.0
        pose.heading = self.heading
        pose.linear_velocity.x = self.v * cos_h
        pose.linear_velocity.y = self.v * sin_h
        pose.linear_acceleration.x = self.accel * cos_h
        pose.linear_acceleration.y = self.accel * sin_h
        pose.angular_velocity.z = yaw_rate
        pose.linear_acceleration_vrf.y = self.accel
        pose.angular_velocity_vrf.z = yaw_rate
        self.loc_writer.write(loc)

        ch = Chassis()
        ch.header.timestamp_sec = now
        ch.header.module_name = 'kairo_virtual_vehicle'
        ch.header.sequence_num = self.seq
        ch.engine_started = True
        ch.speed_mps = abs(self.v)
        ch.throttle_percentage = self.throttle * 100
        ch.brake_percentage = self.brake * 100
        ch.steering_percentage = self.steer / self.MAX_STEER_RAD * 100
        ch.gear_location = Chassis.GearPosition.Value({
            'P': 'GEAR_PARKING', 'R': 'GEAR_REVERSE',
            'N': 'GEAR_NEUTRAL', 'D': 'GEAR_DRIVE'}[self.gear])
        ch.driving_mode = Chassis.COMPLETE_MANUAL
        ch.parking_brake = self.gear == 'P'
        ch.signal.CopyFrom(self.signal)
        self.chassis_writer.write(ch)

    def _loop(self):
        period = 1.0 / self.RATE_HZ
        last = time.time()
        while not cyber.is_shutdown():
            started = time.time()
            with self.lock:
                if not self.active:
                    return
                yaw_rate = self._step(min(max(started - last, 1e-3), 0.1))
                last = started
                self._publish(yaw_rate)
            time.sleep(max(0.0, period - (time.time() - started)))


# --------------------------------------------------------------------------
# Daemon
# --------------------------------------------------------------------------

class Daemon(object):
    def __init__(self):
        self.node = cyber.Node('kairo_gateway_%d' % os.getpid())
        self.map_cache = MapCache()
        self.command_id = int(time.time()) % 1000000 * 10
        self.active_command_id = None

        self.chassis = None
        self.pose = None
        self.planning = None
        self.obstacles = []
        self.hmi = None
        self.route = None
        self.command_status = None
        self.last_rx = {}
        self.last_input = time.time()

        # Chassis and pose arrive at up to 100 Hz and planning at 10 Hz, but
        # telemetry goes out at 5 Hz. Raw readers only keep the newest bytes;
        # they are decoded once per telemetry tick, and only when they changed.
        self._raw = {}       # channel -> latest serialized message
        self._decoded = {}   # channel -> bytes last decoded
        self._lazy = (
            ('chassis', Chassis, self.on_chassis),
            ('localization', LocalizationEstimate, self.on_pose),
            ('planning', ADCTrajectory, self.on_planning),
            ('perception', PerceptionObstacles, self.on_obstacles),
            ('hmi', HMIStatus, self.on_hmi),
        )
        channels = {
            'chassis': '/apollo/canbus/chassis',
            'localization': '/apollo/localization/pose',
            'planning': '/apollo/planning',
            'perception': '/apollo/perception/obstacles',
            'hmi': '/apollo/hmi/status',
        }
        n = self.node
        for key, _, _ in self._lazy:
            n.create_rawdata_reader(channels[key], self._store_raw, key)
        # Rare and needed exactly once per route, so decoded on arrival.
        n.create_reader('/apollo/planning/command', PlanningCommand,
                        self.on_planning_command)

        self.action_client = n.create_client(
            '/apollo/external_command/action', ActionCommand, CommandStatus)
        self.lane_follow_client = n.create_client(
            '/apollo/external_command/lane_follow', LaneFollowCommand,
            CommandStatus)
        self.status_client = n.create_client(
            '/apollo/external_command/command_status', CommandStatusRequest,
            CommandStatus)
        self.chassis_client = n.create_client(
            '/apollo/external_command/chassis', ChassisCommand, CommandStatus)
        self.vehicle = VirtualVehicle(n)
        self.traffic = TrafficSim(n, self.map_cache, self.ego_for_traffic)
        # A daemon that died while traffic ran left Sim Control's dummy
        # predictions switched off; give /apollo/prediction back to it.
        self.traffic.release_prediction()
        self._static_sent = {}  # key -> (value object, time sent)

    def ego_for_traffic(self):
        with _state_lock:
            speed = (self.chassis or {}).get('speed_mps') or 0.0
            route = (self.route or {}).get('polyline')
            return self.pose, speed, route

    def _mark(self, channel):
        self.last_rx[channel] = time.time()

    def _store_raw(self, data, channel):
        with _state_lock:
            self._raw[channel] = data
            self.last_rx[channel] = time.time()

    def decode_pending(self):
        """Decode the newest message of each lazily read channel."""
        for key, msg_type, handler in self._lazy:
            with _state_lock:
                data = self._raw.get(key)
            if data is None or data == self._decoded.get(key):
                continue
            self._decoded[key] = data
            msg = msg_type()
            try:
                msg.ParseFromString(data)
                handler(msg)
            except Exception as e:  # noqa: BLE001
                sys.stderr.write('decode %s failed: %s\n' % (key, e))

    # ---- readers ---------------------------------------------------------

    def on_chassis(self, msg):
        signal = msg.signal
        data = {
            'speed_mps': finite(msg.speed_mps, 0.0),
            'throttle': finite(msg.throttle_percentage),
            'brake': finite(msg.brake_percentage),
            'steering': finite(msg.steering_percentage),
            'gear': Chassis.GearPosition.Name(msg.gear_location)
            if msg.HasField('gear_location') else None,
            'driving_mode': Chassis.DrivingMode.Name(msg.driving_mode),
            'battery_soc': msg.battery_soc_percentage
            if msg.battery_soc_percentage >= 0 else None,
            'fuel_range_m': msg.fuel_range_m
            if msg.HasField('fuel_range_m') else None,
            'engine_started': msg.engine_started,
            'parking_brake': msg.parking_brake,
            'error_code': Chassis.ErrorCode.Name(msg.error_code),
            'signal': {
                'turn': signal.TurnSignal.Name(signal.turn_signal)
                if signal.HasField('turn_signal') else None,
                'high_beam': signal.high_beam,
                'low_beam': signal.low_beam,
                'horn': signal.horn,
                'emergency_light': signal.emergency_light,
            },
        }
        with _state_lock:
            self.chassis = data

    def on_pose(self, msg):
        pose = msg.pose
        data = {
            'x': finite(pose.position.x, ndigits=2),
            'y': finite(pose.position.y, ndigits=2),
            'heading': finite(pose.heading, 0.0, 4),
            'vx': finite(pose.linear_velocity.x, 0.0),
            'vy': finite(pose.linear_velocity.y, 0.0),
        }
        with _state_lock:
            self.pose = data

    def on_planning(self, msg):
        pts = msg.trajectory_point
        step = max(1, len(pts) // MAX_TRAJECTORY_POINTS)
        traj = [[round(p.path_point.x, 1), round(p.path_point.y, 1)]
                for p in list(pts)[::step]]
        decision = None
        if msg.HasField('decision') and msg.decision.HasField('main_decision'):
            decision = msg.decision.main_decision.WhichOneof('task')
        target_speed = None
        if len(pts):
            target_speed = finite(max(p.v for p in pts), ndigits=2)
        data = {
            'trajectory': traj,
            'total_path_length': finite(msg.total_path_length, 0.0, 1),
            'total_path_time': finite(msg.total_path_time, 0.0, 1),
            'is_estop': msg.estop.is_estop,
            'estop_reason': msg.estop.reason or None,
            'main_decision': decision,
            'max_planned_speed': target_speed,
            'is_replan': msg.is_replan,
        }
        with _state_lock:
            self.planning = data

    def on_obstacles(self, msg):
        obs = []
        for o in list(msg.perception_obstacle)[:MAX_OBSTACLES]:
            obs.append({
                'id': o.id,
                'type': PerceptionObstacle.Type.Name(o.type),
                'x': round(o.position.x, 1),
                'y': round(o.position.y, 1),
                'heading': round(o.theta, 3),
                'length': round(o.length, 1),
                'width': round(o.width, 1),
                'speed': round(math.hypot(o.velocity.x, o.velocity.y), 1),
            })
        with _state_lock:
            self.obstacles = obs

    def on_hmi(self, msg):
        data = {
            'current_mode': msg.current_mode,
            'modes': list(msg.modes),
            'current_map': msg.current_map,
            'maps': list(msg.maps),
            'current_vehicle': msg.current_vehicle,
            'vehicles': list(msg.vehicles),
            'modules': dict(msg.modules),
            'modules_lock': dict(msg.modules_lock),
            'monitored_components': {
                k: {'status': ComponentStatus.Status.Name(v.status),
                    'message': v.message or None}
                for k, v in msg.monitored_components.items()
            },
            'current_operation': HMIModeOperation.Name(msg.current_operation)
            if msg.HasField('current_operation') else None,
            'operations': [HMIModeOperation.Name(o) for o in msg.operations],
            'passenger_msg': msg.passenger_msg or None,
        }
        with _state_lock:
            self.hmi = data

    def on_planning_command(self, msg):
        if not msg.HasField('lane_follow_command'):
            return
        routing = msg.lane_follow_command
        try:
            line = self.map_cache.route_polyline(routing)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('route polyline failed: %s\n' % e)
            line = []
        data = {
            'command_id': msg.command_id,
            'distance_m': finite(routing.measurement.distance, None, 1),
            'polyline': line,
            'target_speed': finite(msg.target_speed)
            if msg.HasField('target_speed') else None,
            'received_at': time.time(),
        }
        with _state_lock:
            self.route = data
            self._mark('planning_command')

    # ---- telemetry -------------------------------------------------------

    def snapshot(self):
        now = time.time()
        # Outside _state_lock: the traffic thread takes its own lock first
        # and then _state_lock (for the ego pose); never the other way round.
        traffic = self.traffic.summary()
        with _state_lock:
            ages = {k: round(now - v, 2) for k, v in self.last_rx.items()}
            snap = {
                'type': 'telemetry',
                'ts': now,
                'chassis': self.chassis,
                'pose': self.pose,
                'planning': self.planning,
                'obstacles': self.obstacles,
                'command_status': self.command_status,
                'channel_age_s': ages,
                'manual': self.vehicle.snapshot(),
                'traffic': traffic,
            }
            static = {'hmi': self.hmi, 'route': self.route}
        # HMI status and the route are large and rarely change: include them
        # only when they did (the gateway merges telemetry onto the last).
        for key, value in static.items():
            sent = self._static_sent.get(key)
            if sent is None or sent[0] is not value or now - sent[1] > RESEND_STATIC_S:
                snap[key] = value
                self._static_sent[key] = (value, now)
        return snap

    def poll_command_status(self):
        if self.active_command_id is None:
            return
        req = CommandStatusRequest()
        req.header.timestamp_sec = time.time()
        req.header.module_name = 'kairo_gateway'
        req.command_id = self.active_command_id
        resp = self.status_client.send_request(req)
        if resp is None:
            return
        status = {
            'command_id': resp.command_id,
            'status': CommandStatusType.Name(resp.status),
            'message': resp.message or None,
        }
        with _state_lock:
            self.command_status = status

    def telemetry_loop(self):
        last_status_poll = 0.0
        while not cyber.is_shutdown():
            if time.time() - self.last_input > HEARTBEAT_TIMEOUT_S:
                sys.stderr.write('no heartbeat from gateway; exiting\n')
                os._exit(0)
            self.decode_pending()
            if time.time() - last_status_poll > 1.0:
                last_status_poll = time.time()
                try:
                    self.poll_command_status()
                except Exception as e:  # noqa: BLE001
                    sys.stderr.write('status poll failed: %s\n' % e)
            emit(self.snapshot())
            # Full rate only while something moves; a parked car needs
            # 2 updates/s at most (the gateway sends only changes anyway).
            with _state_lock:
                speed = (self.chassis or {}).get('speed_mps') or 0.0
            busy = speed > 0.05 or self.vehicle.active
            time.sleep(TELEMETRY_PERIOD_S if busy else IDLE_PERIOD_S)

    # ---- commands --------------------------------------------------------

    def next_command_id(self):
        self.command_id += 1
        return self.command_id

    def cmd_ping(self, _req):
        return {'pong': True, 'map_dir': current_map_dir()}

    def cmd_lane_follow(self, req):
        cmd = LaneFollowCommand()
        cmd.header.timestamp_sec = time.time()
        cmd.header.module_name = 'kairo_gateway'
        cmd.command_id = self.next_command_id()
        cmd.end_pose.x = float(req['x'])
        cmd.end_pose.y = float(req['y'])
        if req.get('heading') is not None:
            cmd.end_pose.heading = float(req['heading'])
        if req.get('target_speed'):
            cmd.target_speed = float(req['target_speed'])
        resp = self.lane_follow_client.send_request(cmd)
        return self._command_result(cmd.command_id, resp)

    def cmd_action(self, req):
        name = str(req['command']).upper()
        cmd = ActionCommand()
        cmd.header.timestamp_sec = time.time()
        cmd.header.module_name = 'kairo_gateway'
        cmd.command_id = self.next_command_id()
        cmd.command = ActionCommandType.Value(name)
        resp = self.action_client.send_request(cmd)
        return self._command_result(cmd.command_id, resp, track=False)

    def _command_result(self, command_id, resp, track=True):
        if resp is None:
            raise RuntimeError('No response from external_command service '
                               '(is the planning/external_command process '
                               'running?)')
        status = CommandStatusType.Name(resp.status)
        if track and status != 'ERROR':
            self.active_command_id = command_id
        result = {
            'command_id': command_id,
            'status': status,
            'message': resp.message or None,
        }
        if track:
            with _state_lock:
                self.command_status = result
        if status == 'ERROR':
            raise RuntimeError(resp.message or 'Apollo rejected the command')
        return result

    def cmd_signals(self, req):
        """Lights/horn/turn signals as an Apollo ChassisCommand (actuated by
        canbus on a real vehicle) and on the virtual vehicle's chassis."""
        signal = VehicleSignal()
        signal.turn_signal = VehicleSignal.TurnSignal.Value(
            req.get('turn') or 'TURN_NONE')
        signal.high_beam = bool(req.get('high_beam'))
        signal.low_beam = bool(req.get('low_beam'))
        signal.horn = bool(req.get('horn'))
        signal.emergency_light = bool(req.get('emergency_light'))
        self.vehicle.set_signal(signal)

        cmd = ChassisCommand()
        cmd.header.timestamp_sec = time.time()
        cmd.header.module_name = 'kairo_gateway'
        cmd.command_id = self.next_command_id()
        cmd.basic_signal.CopyFrom(signal)
        resp = self.chassis_client.send_request(cmd)
        return {
            'apollo': CommandStatusType.Name(resp.status) if resp else None,
            'message': (resp.message or None) if resp else
            'ChassisCommandProcessor not running',
        }

    def cmd_manual_start(self, req):
        self.vehicle.start(req['x'], req['y'], req['heading'],
                           req.get('speed'), req.get('gear'))
        return self.vehicle.snapshot()

    def cmd_manual_stop(self, _req):
        return self.vehicle.stop()

    def cmd_gear(self, req):
        if not self.vehicle.active:
            raise RuntimeError('Gear can only be changed while driving manually')
        self.vehicle.set_gear(str(req['gear']).upper())
        return self.vehicle.snapshot()

    def cmd_snap(self, req):
        heading = req.get('heading')
        return self.map_cache.snap(float(req['x']), float(req['y']),
                                   float(req.get('radius', 25.0)),
                                   None if heading is None else float(heading))

    def cmd_traffic_start(self, req):
        return self.traffic.start_traffic(
            count=int(req.get('count', 8)), radius=float(req.get('radius_m', 150.0)),
            seed=req.get('seed'), speed_factor=float(req.get('speed_factor', 1.0)))

    def cmd_traffic_stop(self, _req):
        return self.traffic.stop_traffic()

    def cmd_traffic_status(self, _req):
        return self.traffic.status()

    def cmd_hazard_start(self, req):
        return self.traffic.start_hazard(req['hazard_id'], req['kind'],
                                         req.get('params') or {})

    def cmd_hazard_stop(self, req):
        return self.traffic.stop_hazard(req['hazard_id'])

    def cmd_map_lanes(self, _req):
        payload = self.map_cache.ensure()
        if payload is None:
            raise RuntimeError('No --map_dir found in %s' % GLOBAL_FLAGFILE)
        return payload

    def handle(self, line):
        try:
            req = json.loads(line)
        except ValueError:
            return
        req_id = req.get('id')
        handler = getattr(self, 'cmd_' + str(req.get('cmd')), None)
        if handler is None:
            emit({'type': 'reply', 'id': req_id, 'ok': False,
                  'error': 'unknown command %r' % req.get('cmd')})
            return
        try:
            emit({'type': 'reply', 'id': req_id, 'ok': True,
                  'data': handler(req)})
        except Exception as e:  # noqa: BLE001
            emit({'type': 'reply', 'id': req_id, 'ok': False,
                  'error': str(e)})

    def stdin_loop(self):
        for line in sys.stdin:
            self.last_input = time.time()
            line = line.strip()
            if line == '{"cmd":"heartbeat"}':
                continue
            if line.startswith('{"cmd":"drive"'):
                # ~20 Hz from the tablet: apply inline, no thread, no reply.
                try:
                    req = json.loads(line)
                    self.vehicle.set_input(req.get('throttle', 0),
                                           req.get('brake', 0),
                                           req.get('steer', 0))
                except (ValueError, TypeError):
                    pass
                continue
            if line:
                # Service calls block, so each request gets its own thread.
                threading.Thread(target=self.handle, args=(line,),
                                 daemon=True).start()
        # Gateway closed the pipe: exit.
        cyber.shutdown()
        os._exit(0)


def main():
    cyber.init('kairo_gateway')
    daemon = Daemon()
    threading.Thread(target=daemon.telemetry_loop, daemon=True).start()
    emit({'type': 'ready', 'pid': os.getpid(), 'map_dir': current_map_dir()})
    daemon.stdin_loop()


if __name__ == '__main__':
    main()
