import carla
import time
import cv2
import numpy as np
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

latest_image = None

def process_image(image):
    global latest_image
    # Convert carla image to numpy array
    array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
    array = np.reshape(array, (image.height, image.width, 4))
    array = array[:, :, :3] # remove alpha
    
    # encode to jpeg
    ret, jpeg = cv2.imencode('.jpg', array)
    if ret:
        latest_image = jpeg.tobytes()

class CamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith('.mjpg'):
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
            self.end_headers()
            while True:
                if latest_image is not None:
                    try:
                        self.wfile.write(b"--jpgboundary\r\n")
                        self.send_header('Content-type', 'image/jpeg')
                        self.send_header('Content-length', str(len(latest_image)))
                        self.end_headers()
                        self.wfile.write(latest_image)
                        self.wfile.write(b"\r\n")
                        time.sleep(0.05)
                    except Exception:
                        break
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><body><img src='/cam.mjpg' width='800' /></body></html>")

def main():
    print("Connecting to Carla...")
    client = carla.Client("172.31.128.1", 2000)
    client.set_timeout(10.0)
    world = client.get_world()

    blueprint_library = world.get_blueprint_library()
    vehicle_bp = blueprint_library.filter('vehicle.lincoln.mkz_2017')[0]
    vehicle_bp.set_attribute('role_name', 'hero')

    spawn_points = world.get_map().get_spawn_points()
    spawn_point = spawn_points[0] if spawn_points else carla.Transform()
    
    ego_vehicle = world.try_spawn_actor(vehicle_bp, spawn_point)
    if ego_vehicle is None:
        print("Failed to spawn vehicle")
        return
        
    camera_bp = blueprint_library.find('sensor.camera.rgb')
    camera_transform = carla.Transform(carla.Location(x=1.5, z=2.4))
    camera = world.spawn_actor(camera_bp, camera_transform, attach_to=ego_vehicle)
    
    camera.listen(lambda image: process_image(image))
    print("Camera spawned and listening!")

    server = HTTPServer(('0.0.0.0', 8080), CamHandler)
    print("Server started at http://localhost:8080")
    server.serve_forever()

if __name__ == '__main__':
    main()
