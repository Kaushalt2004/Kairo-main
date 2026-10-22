"""KAIRO traffic and hazard simulation - runs INSIDE the Apollo container.

Loaded by cyber_daemon.py (copied next to it). Simulated vehicles drive along
the HD map's lanes and the in-world hazards (phantom obstacle, cut-in,
perception dropout) are injected here. Every 100 ms while anything is active
it publishes

  /apollo/perception/obstacles  PerceptionObstacles - what Dreamview and the
                                KAIRO gateway/tablet show
  /apollo/prediction            PredictionObstacles - what planning reacts
                                to, with each vehicle's future path

Apollo's Prediction module is not needed (and must stay off while traffic
runs, or two publishers would fight over /apollo/prediction). Dreamview's
Sim Control normally publishes empty "dummy" predictions to trigger
planning; it stops as soon as it sees ours and only resumes after a message
named "SimPrediction", so one such message is published when traffic stops.

Vehicles follow the Intelligent Driver Model behind the next vehicle on
their lane path, and always yield to the ego car when it is in front of
them. Must stay compatible with the container's Python 3.6.
"""

import math
import random
import threading
import time

from modules.common_msgs.perception_msgs.perception_obstacle_pb2 import (  # noqa: E402
    PerceptionObstacle, PerceptionObstacles)
from modules.common_msgs.prediction_msgs.prediction_obstacle_pb2 import (  # noqa: E402
    PredictionObstacles)

RATE_HZ = 10.0
HORIZON_S = 8.0           # predicted trajectory length
HORIZON_STEP_S = 0.25
DEFAULT_SPEED_MPS = 30 / 3.6
EGO_REAR_TO_CENTER = 1.45  # Apollo's pose is the rear axle; the car is 4.93 m long
EGO_LENGTH, EGO_WIDTH = 4.93, 2.11

# Intelligent Driver Model parameters
IDM_ACCEL = 1.5           # m/s^2
IDM_DECEL = 2.5           # comfortable braking, m/s^2
IDM_GAP = 4.0             # standstill gap, m
IDM_HEADWAY = 1.5         # s
MAX_BRAKE = 6.0           # m/s^2
LOOK_AHEAD_M = 70.0
EGO_LATERAL_M = 2.2       # ego counts as "in front" within this lateral offset
PATH_CHECK_M = 30.0       # how far along its path a vehicle checks for the ego

PREDICTION_CHANNEL = '/apollo/prediction'
PERCEPTION_CHANNEL = '/apollo/perception/obstacles'


def _wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class LaneGeometry(object):
    """Arc-length lookup on the map's lane centre-lines (memoized)."""

    def __init__(self, map_cache):
        self.map_cache = map_cache
        self._cum = {}

    def cum(self, lane_id):
        c = self._cum.get(lane_id)
        if c is None:
            pts = self.map_cache.lanes[lane_id]
            c = [0.0]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                c.append(c[-1] + math.hypot(bx - ax, by - ay))
            self._cum[lane_id] = c
        return c

    def length(self, lane_id):
        return self.cum(lane_id)[-1]

    def pose(self, lane_id, s, d=0.0):
        """(x, y, heading) at arc length s, shifted d metres to the left."""
        pts, cum = self.map_cache.lanes[lane_id], self.cum(lane_id)
        s = min(max(s, 0.0), cum[-1])
        lo, hi = 0, len(cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        (ax, ay), (bx, by) = pts[lo], pts[hi]
        seg = cum[hi] - cum[lo]
        t = (s - cum[lo]) / seg if seg > 0 else 0.0
        heading = math.atan2(by - ay, bx - ax)
        x, y = ax + t * (bx - ax), ay + t * (by - ay)
        return x - d * math.sin(heading), y + d * math.cos(heading), heading

    def project(self, lane_id, x, y):
        """(s, signed lateral offset, left positive) of a point on a lane."""
        pts, cum = self.map_cache.lanes[lane_id], self.cum(lane_id)
        best = None
        for i in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[i], pts[i + 1]
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            if seg2 == 0:
                continue
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / seg2))
            px, py = ax + t * dx, ay + t * dy
            d2 = (px - x) ** 2 + (py - y) ** 2
            if best is None or d2 < best[0]:
                side = dx * (y - ay) - dy * (x - ax)
                best = (d2, cum[i] + t * math.sqrt(seg2),
                        math.copysign(math.sqrt(d2), side))
        return (best[1], best[2]) if best else (0.0, 0.0)


class SimVehicle(object):
    """A vehicle on a lane (traffic, cut-in) or at a fixed pose (phantom)."""

    def __init__(self, vid, kind, length=4.6, width=1.9, height=1.5,
                 obstacle_type='VEHICLE'):
        self.id = vid
        self.kind = kind            # traffic | phantom | cut_in
        self.length, self.width, self.height = length, width, height
        self.type = obstacle_type
        self.lane = None
        self.s = 0.0
        self.plan = []              # upcoming lane ids
        self.v = 0.0
        self.v_des = DEFAULT_SPEED_MPS
        self.d = 0.0                # lateral offset from the lane centre
        self.d_rate = 0.0           # m/s towards 0 (lane change)
        self.x = self.y = self.heading = 0.0
        self.born = time.time()
        self.expires_at = None
        self.hazard_id = None
        self.pending = None         # scripted action (cut-in lane change)

    @property
    def static(self):
        return self.lane is None or (self.v < 0.1 and self.kind == 'phantom')

    def summary(self):
        return {'id': self.id, 'kind': self.kind, 'x': round(self.x, 1),
                'y': round(self.y, 1), 'speed': round(self.v, 1)}


class TrafficSim(object):
    def __init__(self, node, map_cache, ego):
        """ego() -> (pose dict or None, speed m/s, route polyline or None)."""
        self.geo = LaneGeometry(map_cache)
        self.map_cache = map_cache
        self.ego = ego
        self.perception_writer = node.create_writer(PERCEPTION_CHANNEL, PerceptionObstacles)
        self.prediction_writer = node.create_writer(PREDICTION_CHANNEL, PredictionObstacles)
        self.lock = threading.RLock()
        self.vehicles = {}          # id -> SimVehicle
        self.rng = random.Random(1)
        self.config = None          # traffic settings while traffic runs
        self.dropout_until = 0.0
        self.dropout_hazard = None
        self.seq = 0
        self._next_id = {'traffic': 10001, 'phantom': 20001, 'cut_in': 30001}
        self._thread = None
        self._was_active = False
        self._last_keep_near = 0.0

    # ---- public commands (called from the daemon's request threads) ------

    def start_traffic(self, count=8, radius=150.0, seed=None, speed_factor=1.0):
        self.map_cache.ensure()
        with self.lock:
            self.stop_traffic()
            self.rng = random.Random(seed if seed is not None else int(time.time()))
            self.config = {'count': int(count), 'radius': float(radius),
                           'seed': seed, 'speed_factor': float(speed_factor)}
            for _ in range(int(count)):
                v = self._spawn_traffic()
                if v is None:
                    break
            self._ensure_thread()
            return self.status()

    def stop_traffic(self):
        with self.lock:
            self.config = None
            for vid in [k for k, v in self.vehicles.items() if v.kind == 'traffic']:
                del self.vehicles[vid]
        return self.status()

    def start_hazard(self, hazard_id, kind, params):
        self.map_cache.ensure()
        duration = float(params.get('duration_s') or 10.0)
        with self.lock:
            if kind == 'perception_dropout':
                self.dropout_until = time.time() + duration
                self.dropout_hazard = hazard_id
                self._ensure_thread()
                return {'until': self.dropout_until}
            if kind == 'phantom_obstacle':
                v = self._spawn_phantom(float(params.get('ahead_m') or 25.0),
                                        params.get('object') or 'vehicle')
            elif kind == 'cut_in':
                v = self._spawn_cut_in(float(params.get('ahead_m') or 25.0),
                                       params.get('side') or 'auto',
                                       float(params.get('speed_factor') or 0.6),
                                       float(params.get('delay_s') or 1.0),
                                       float(params.get('change_s') or 3.0))
            else:
                raise RuntimeError('Unknown in-world hazard %r' % kind)
            v.hazard_id = hazard_id
            v.expires_at = time.time() + duration
            self.vehicles[v.id] = v
            self._ensure_thread()
            return {'obstacle_id': v.id, 'x': round(v.x, 2), 'y': round(v.y, 2),
                    'heading': round(v.heading, 3)}

    def stop_hazard(self, hazard_id):
        with self.lock:
            if self.dropout_hazard == hazard_id:
                self.dropout_until = 0.0
                self.dropout_hazard = None
            for vid in [k for k, v in self.vehicles.items() if v.hazard_id == hazard_id]:
                del self.vehicles[vid]
        return self.status()

    def status(self):
        with self.lock:
            kinds = {}
            for v in self.vehicles.values():
                kinds[v.kind] = kinds.get(v.kind, 0) + 1
            return {
                'traffic': dict(self.config) if self.config else None,
                'counts': kinds,
                'dropout': time.time() < self.dropout_until,
                'vehicles': [v.summary() for v in self.vehicles.values()],
            }

    def summary(self):
        """Small status for every telemetry message."""
        with self.lock:
            return {'on': self.config is not None,
                    'vehicles': sum(1 for v in self.vehicles.values() if v.kind == 'traffic'),
                    'hazard_obstacles': sum(1 for v in self.vehicles.values() if v.kind != 'traffic'),
                    'dropout': time.time() < self.dropout_until}

    def release_prediction(self):
        """Hand /apollo/prediction back to Sim Control's dummy publisher."""
        msg = PredictionObstacles()
        msg.header.timestamp_sec = time.time()
        msg.header.module_name = 'SimPrediction'
        self.prediction_writer.write(msg)

    # ---- spawning ----------------------------------------------------------

    def _new(self, kind, **kw):
        vid = self._next_id[kind]
        self._next_id[kind] += 1
        return SimVehicle(vid, kind, **kw)

    def _ego_center(self):
        pose, speed, _ = self.ego()
        if not pose:
            return None
        h = pose['heading']
        return (pose['x'] + EGO_REAR_TO_CENTER * math.cos(h),
                pose['y'] + EGO_REAR_TO_CENTER * math.sin(h), h, speed)

    def _spawn_traffic(self):
        ego = self._ego_center()
        boxes = self.map_cache.lane_boxes
        if ego:
            cx, cy = ego[0], ego[1]
        else:
            xs = [b[0] for b in boxes.values()] + [b[2] for b in boxes.values()]
            ys = [b[1] for b in boxes.values()] + [b[3] for b in boxes.values()]
            cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        r = self.config['radius']
        candidates = [lid for lid, (x0, y0, x1, y1) in boxes.items()
                      if x0 - r < cx < x1 + r and y0 - r < cy < y1 + r
                      and self.geo.length(lid) >= 25.0]
        for _ in range(60):
            if not candidates:
                return None
            lane = self.rng.choice(candidates)
            s = self.rng.uniform(5.0, self.geo.length(lane) - 5.0)
            x, y, h = self.geo.pose(lane, s)
            if math.hypot(x - cx, y - cy) > r:
                continue
            if ego and math.hypot(x - ego[0], y - ego[1]) < 25.0:
                continue
            if any(math.hypot(x - o.x, y - o.y) < 15.0 for o in self.vehicles.values()):
                continue
            v = self._new('traffic')
            v.lane, v.s = lane, s
            limit = self.map_cache.speed_limits.get(lane) or DEFAULT_SPEED_MPS
            v.v_des = max(4.0, min(limit, 14.0) * self.rng.uniform(0.6, 0.95)
                          * self.config['speed_factor'])
            v.v = v.v_des * 0.5
            v.x, v.y, v.heading = x, y, h
            self.vehicles[v.id] = v
            return v
        return None

    def _ego_lane(self):
        pose, _, _ = self.ego()
        if not pose:
            raise RuntimeError('No ego pose: start Sim Control first')
        hit = self.map_cache.snap(pose['x'], pose['y'], 6.0, pose['heading'])
        if not hit:
            raise RuntimeError('The car is not on a lane')
        s, _ = self.geo.project(hit['lane_id'], pose['x'], pose['y'])
        return hit['lane_id'], s, pose

    def _point_ahead(self, ahead_m):
        """Point `ahead_m` in front of the car along its route (or lane)."""
        pose, _, route = self.ego()
        lane, s, pose = self._ego_lane()
        if route and len(route) > 1:
            # Route polyline: walk from the vertex closest to the car.
            i0 = min(range(len(route)), key=lambda i: (route[i][0] - pose['x']) ** 2 +
                     (route[i][1] - pose['y']) ** 2)
            left = ahead_m
            for (ax, ay), (bx, by) in zip(route[i0:], route[i0 + 1:]):
                seg = math.hypot(bx - ax, by - ay)
                if seg >= left and seg > 0:
                    t = left / seg
                    return (ax + t * (bx - ax), ay + t * (by - ay),
                            math.atan2(by - ay, bx - ax))
                left -= seg
        # No route: follow the lane graph.
        lane, s = self._lane_at(lane, s + ahead_m)
        return self.geo.pose(lane, s)

    def _spawn_phantom(self, ahead_m, obj):
        x, y, h = self._point_ahead(ahead_m)
        if obj == 'debris':
            v = self._new('phantom', length=1.2, width=1.2, height=0.6,
                          obstacle_type='UNKNOWN_UNMOVABLE')
        else:
            v = self._new('phantom')
        v.x, v.y, v.heading = x, y, h
        return v

    def _spawn_cut_in(self, ahead_m, side, speed_factor, delay_s, change_s):
        lane, s, pose = self._ego_lane()
        _, ego_speed, _ = self.ego()
        # The lane the car will be on `ahead_m` from now, and its neighbours.
        lane, s = self._lane_at(lane, s + ahead_m)
        neigh = {'left': self.map_cache.left_neighbors.get(lane) or [],
                 'right': self.map_cache.right_neighbors.get(lane) or []}
        if side == 'auto':
            side = 'left' if neigh['left'] else 'right'
        if not neigh.get(side):
            raise RuntimeError('No same-direction lane on the %s, %.0f m ahead of '
                               'the car, for a vehicle to cut in from' % (side, ahead_m))
        target = self.geo.pose(lane, s)
        n_lane = neigh[side][0]
        n_s, _ = self.geo.project(n_lane, target[0], target[1])
        v = self._new('cut_in')
        v.lane, v.s = n_lane, n_s
        v.v = v.v_des = max(3.0, ego_speed * speed_factor)
        v.x, v.y, v.heading = self.geo.pose(n_lane, n_s)
        v.pending = {'at': time.time() + delay_s, 'into': lane, 'change_s': change_s}
        return v

    def _lane_at(self, lane, s):
        """(lane, s) reached by driving s metres from the start of `lane`."""
        while s > self.geo.length(lane):
            succ = self.map_cache.successors.get(lane) or []
            if not succ:
                return lane, self.geo.length(lane)
            s -= self.geo.length(lane)
            lane = succ[0]
        return lane, s

    # ---- simulation --------------------------------------------------------

    def _extend_plan(self, v, needed):
        ahead = self.geo.length(v.lane) - v.s + sum(self.geo.length(l) for l in v.plan)
        last = v.plan[-1] if v.plan else v.lane
        while ahead < needed:
            succ = self.map_cache.successors.get(last) or []
            if not succ:
                return False
            last = self.rng.choice(succ)
            v.plan.append(last)
            ahead += self.geo.length(last)
        return True

    def _gap_ahead(self, v, by_lane, ego):
        """(gap m, leader speed) to the closest vehicle in front of v."""
        best = (float('inf'), 0.0)
        offset = -v.s
        for lane in [v.lane] + v.plan:
            if offset > LOOK_AHEAD_M:
                break
            for o in by_lane.get(lane, ()):
                if o is v:
                    continue
                dist = offset + o.s
                if dist > 0:
                    gap = dist - (v.length + o.length) / 2
                    if gap < best[0]:
                        best = (gap, o.v)
            offset += self.geo.length(lane)
        for o in self.vehicles.values():
            if o.lane is None:  # phantom obstacles block whoever is behind them
                fwd, lat = self._rel(v, o.x, o.y)
                if 0 < fwd < LOOK_AHEAD_M and abs(lat) < 1.6:
                    best = min(best, (fwd - (v.length + o.length) / 2, 0.0))
        if ego:
            fwd, lat = self._rel(v, ego[0], ego[1])
            if 0 < fwd < LOOK_AHEAD_M and abs(lat) < EGO_LATERAL_M:
                best = min(best, (fwd - (v.length + EGO_LENGTH) / 2, ego[3]))
            hit = self._ego_on_path(v, ego)
            if hit is not None:
                best = min(best, (hit - v.length / 2 - 1.0, ego[3]))
        return best

    def _ego_on_path(self, v, ego):
        """Distance along v's lane path to the first point where the path
        comes within half a car width of the ego's footprint (curved paths
        through junctions, which a straight look-ahead misses)."""
        ex, ey, eh = ego[0], ego[1], ego[2]
        if math.hypot(ex - v.x, ey - v.y) > PATH_CHECK_M + EGO_LENGTH:
            return None
        c, s = math.cos(eh), math.sin(eh)
        clearance = v.width / 2 + 0.4
        dist, step = 0.0, 1.5
        lane_i, lanes, ls = 0, [v.lane] + v.plan, v.s
        while dist < PATH_CHECK_M:
            ls += step
            dist += step
            while ls > self.geo.length(lanes[lane_i]):
                if lane_i + 1 >= len(lanes):
                    return None
                ls -= self.geo.length(lanes[lane_i])
                lane_i += 1
            px, py, _ = self.geo.pose(lanes[lane_i], ls)
            dx, dy = px - ex, py - ey
            lx, ly = dx * c + dy * s, -dx * s + dy * c
            out_x = max(abs(lx) - EGO_LENGTH / 2, 0.0)
            out_y = max(abs(ly) - EGO_WIDTH / 2, 0.0)
            if math.hypot(out_x, out_y) < clearance:
                return dist
        return None

    @staticmethod
    def _rel(v, x, y):
        dx, dy = x - v.x, y - v.y
        c, s = math.cos(v.heading), math.sin(v.heading)
        return dx * c + dy * s, -dx * s + dy * c

    def _step(self, dt):
        now = time.time()
        ego = self._ego_center()
        for vid in [k for k, v in self.vehicles.items()
                    if v.expires_at is not None and now > v.expires_at]:
            del self.vehicles[vid]
        if self.dropout_until and now > self.dropout_until:
            self.dropout_until, self.dropout_hazard = 0.0, None

        by_lane = {}
        for v in self.vehicles.values():
            if v.lane is not None:
                by_lane.setdefault(v.lane, []).append(v)

        for v in list(self.vehicles.values()):
            if v.lane is None:
                continue
            if v.pending and now >= v.pending['at']:
                # Cut-in: move onto the car's lane, keeping the position.
                into = v.pending['into']
                s, d = self.geo.project(into, v.x, v.y)
                v.lane, v.s, v.d, v.plan = into, s, d, []
                v.d_rate = abs(d) / max(v.pending['change_s'], 0.5)
                v.pending = None
            if not self._extend_plan(v, v.v * HORIZON_S + LOOK_AHEAD_M):
                if self.geo.length(v.lane) - v.s < 1.0:
                    del self.vehicles[v.id]
                    continue
            gap, lead_v = self._gap_ahead(v, by_lane, ego)
            if gap <= 0.5:
                accel = -MAX_BRAKE
            else:
                s_star = IDM_GAP + max(0.0, v.v * IDM_HEADWAY + v.v * (v.v - lead_v) /
                                       (2 * math.sqrt(IDM_ACCEL * IDM_DECEL)))
                free = 1 - (v.v / max(v.v_des, 0.1)) ** 4
                accel = IDM_ACCEL * (free - (s_star / gap) ** 2 if gap < 1e6 else free)
                accel = max(-MAX_BRAKE, min(IDM_ACCEL, accel))
            v.v = max(0.0, v.v + accel * dt)
            v.s += v.v * dt
            if v.d_rate:
                step = v.d_rate * dt
                v.d = 0.0 if abs(v.d) <= step else v.d - math.copysign(step, v.d)
                if v.d == 0.0:
                    v.d_rate = 0.0
            while v.s > self.geo.length(v.lane) and v.plan:
                v.s -= self.geo.length(v.lane)
                v.lane = v.plan.pop(0)
            v.x, v.y, v.heading = self.geo.pose(v.lane, v.s, v.d)

        if self.config and now - self._last_keep_near > 1.0:
            self._last_keep_near = now
            self._keep_near(ego)

    def _keep_near(self, ego):
        """Respawn traffic that drove far away from the car; top up the count."""
        if ego:
            limit = self.config['radius'] * 1.6
            for vid in [k for k, v in self.vehicles.items() if v.kind == 'traffic' and
                        math.hypot(v.x - ego[0], v.y - ego[1]) > limit]:
                del self.vehicles[vid]
        missing = self.config['count'] - sum(
            1 for v in self.vehicles.values() if v.kind == 'traffic')
        for _ in range(max(0, missing)):
            if self._spawn_traffic() is None:
                break

    # ---- publishing --------------------------------------------------------

    def _fill_obstacle(self, o, v, now):
        o.id = v.id
        o.position.x, o.position.y, o.position.z = v.x, v.y, 0.0
        o.theta = v.heading
        o.velocity.x, o.velocity.y = v.v * math.cos(v.heading), v.v * math.sin(v.heading)
        o.length, o.width, o.height = v.length, v.width, v.height
        o.type = PerceptionObstacle.Type.Value(v.type)
        o.tracking_time = now - v.born
        o.timestamp = now
        o.confidence = 1.0
        c, s = math.cos(v.heading), math.sin(v.heading)
        for fx, fy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
            p = o.polygon_point.add()
            p.x = v.x + fx * v.length / 2 * c - fy * v.width / 2 * s
            p.y = v.y + fx * v.length / 2 * s + fy * v.width / 2 * c
            p.z = 0.0

    def _trajectory(self, traj, v):
        """Constant-speed prediction along the vehicle's lane path."""
        traj.probability = 1.0
        lanes = [v.lane] + v.plan
        lane_i, s, d = 0, v.s, v.d
        dist = 0.0
        steps = int(HORIZON_S / HORIZON_STEP_S) + 1
        for k in range(steps):
            t = k * HORIZON_STEP_S
            x, y, h = self.geo.pose(lanes[lane_i], s, d)
            p = traj.trajectory_point.add()
            p.path_point.x, p.path_point.y, p.path_point.theta = x, y, h
            p.path_point.s = dist
            p.v, p.a, p.relative_time = v.v, 0.0, t
            step = v.v * HORIZON_STEP_S
            dist += step
            s += step
            if v.d_rate:
                dd = v.d_rate * HORIZON_STEP_S
                d = 0.0 if abs(d) <= dd else d - math.copysign(dd, d)
            while s > self.geo.length(lanes[lane_i]) and lane_i + 1 < len(lanes):
                s -= self.geo.length(lanes[lane_i])
                lane_i += 1

    def _publish(self):
        now = time.time()
        self.seq += 1
        visible = [] if now < self.dropout_until else list(self.vehicles.values())

        per = PerceptionObstacles()
        per.header.timestamp_sec = now
        per.header.module_name = 'kairo_traffic'
        per.header.sequence_num = self.seq
        pred = PredictionObstacles()
        pred.header.timestamp_sec = now
        pred.header.module_name = 'kairo_traffic'
        pred.header.sequence_num = self.seq
        pred.start_timestamp = now
        pred.end_timestamp = now
        for v in visible:
            self._fill_obstacle(per.perception_obstacle.add(), v, now)
            po = pred.prediction_obstacle.add()
            self._fill_obstacle(po.perception_obstacle, v, now)
            po.timestamp = now
            po.predicted_period = HORIZON_S
            po.priority.priority = po.priority.NORMAL
            po.is_static = v.static or v.v < 0.1
            if not po.is_static:
                self._trajectory(po.trajectory.add(), v)
        self.perception_writer.write(per)
        self.prediction_writer.write(pred)

    def _active(self):
        return bool(self.vehicles) or self.config is not None or \
            time.time() < self.dropout_until

    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self):
        period = 1.0 / RATE_HZ
        last = time.time()
        while True:
            started = time.time()
            with self.lock:
                active = self._active()
                if active:
                    self._step(min(max(started - last, 1e-3), 0.3))
                    self._publish()
                    self._was_active = True
                elif self._was_active:
                    # Empty once (clears Dreamview), then hand prediction back.
                    self._publish()
                    self.release_prediction()
                    self._was_active = False
                    self._thread = None
                    return
            last = started
            time.sleep(max(0.0, period - (time.time() - started)))
