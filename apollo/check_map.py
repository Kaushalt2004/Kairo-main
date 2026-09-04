import carla
client = carla.Client('172.31.128.1', 2000)
client.set_timeout(5.0)
print(client.get_world().get_map().name)
