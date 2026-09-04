import carla
import random
import time
import sys

print("Connecting to Carla...", flush=True)
client = carla.Client("172.31.128.1", 2000)
client.set_timeout(10.0)
world = client.get_world()

blueprint_library = world.get_blueprint_library()
vehicle_bp = blueprint_library.filter('vehicle.lincoln.mkz_2017')[0]
vehicle_bp.set_attribute('role_name', 'hero')

spawn_points = world.get_map().get_spawn_points()
spawn_point = random.choice(spawn_points) if spawn_points else carla.Transform()

print("Spawning ego vehicle...", flush=True)
ego_vehicle = world.try_spawn_actor(vehicle_bp, spawn_point)
if ego_vehicle is None:
    print("Failed to spawn ego vehicle!", flush=True)
    sys.exit(1)
print(f"Spawned ego vehicle: {ego_vehicle.id}", flush=True)

print("Spawning camera...", flush=True)
camera_bp = blueprint_library.find('sensor.camera.rgb')
camera_transform = carla.Transform(carla.Location(x=1.5, z=2.4))
camera = world.spawn_actor(camera_bp, camera_transform, attach_to=ego_vehicle)
print(f"Spawned camera: {camera.id}", flush=True)

print("Starting infinite loop...", flush=True)
while True:
    time.sleep(1)
