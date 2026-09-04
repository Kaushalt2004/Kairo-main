import carla
import random

client = carla.Client('172.31.128.1', 2000)
client.set_timeout(5.0)
world = client.get_world()
blueprint_library = world.get_blueprint_library()

# Find the Lincoln MKZ blueprint
bp = blueprint_library.find('vehicle.lincoln.mkz_2017')
bp.set_attribute('role_name', 'hero')

# Choose a random spawn point
spawn_points = world.get_map().get_spawn_points()
spawn_point = spawn_points[0] if spawn_points else carla.Transform(carla.Location(x=0,y=0,z=2))

# Spawn the vehicle
vehicle = world.try_spawn_actor(bp, spawn_point)
if vehicle:
    print("Successfully spawned hero vehicle with ID:", vehicle.id)
    # Also spawn a camera for the bridge to find (run_bridge.py line 345 looks for sensor.camera.rgb)
    cam_bp = blueprint_library.find('sensor.camera.rgb')
    cam_transform = carla.Transform(carla.Location(x=1.5, z=2.4))
    camera = world.spawn_actor(cam_bp, cam_transform, attach_to=vehicle)
    print("Successfully attached RGB camera with ID:", camera.id)
else:
    print("Failed to spawn vehicle. Spawn point might be occupied.")
