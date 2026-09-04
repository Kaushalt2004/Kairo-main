import carla
import time
c = carla.Client("172.31.128.1", 2000)
c.set_timeout(5.0)
w = c.get_world()

# Delete all existing vehicles and sensors to prevent conflicts
for a in w.get_actors().filter('vehicle.*'):
    a.destroy()
for a in w.get_actors().filter('sensor.*'):
    a.destroy()
print("Cleaned up old actors.")

time.sleep(1)

bp_lib = w.get_blueprint_library()
bp = bp_lib.find('vehicle.lincoln.mkz_2017')
bp.set_attribute('role_name', 'hero')

spawn_points = w.get_map().get_spawn_points()
spawn_point = spawn_points[0]

vehicle = w.spawn_actor(bp, spawn_point)
print("Spawned vehicle ID: %d at %s" % (vehicle.id, str(spawn_point.location)))

cam_bp = bp_lib.find('sensor.camera.rgb')
cam_transform = carla.Transform(carla.Location(x=1.5, z=2.4))
camera = w.spawn_actor(cam_bp, cam_transform, attach_to=vehicle)
print("Spawned camera ID: %d" % camera.id)
