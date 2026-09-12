import 'dart:convert';

class TelemetryModel {
  final String vehicleId;
  final DateTime timestamp;
  final int seq;
  final LocationData location;
  final KinematicsData kinematics;
  final ControlsData controls;
  final ComputeData compute;
  final AutonomyData autonomy;
  final List<SensorHealth> sensors;
  final SimulationData? simulation;

  TelemetryModel({
    required this.vehicleId,
    required this.timestamp,
    required this.seq,
    required this.location,
    required this.kinematics,
    required this.controls,
    required this.compute,
    required this.autonomy,
    required this.sensors,
    this.simulation,
  });

  factory TelemetryModel.fromJson(Map<String, dynamic> json) {
    return TelemetryModel(
      vehicleId: json['vehicle_id'] ?? 'UNKNOWN',
      timestamp: DateTime.tryParse(json['timestamp'] ?? '') ?? DateTime.now(),
      seq: json['seq'] ?? 0,
      location: LocationData.fromJson(json['location'] ?? {}),
      kinematics: KinematicsData.fromJson(json['kinematics'] ?? {}),
      controls: ControlsData.fromJson(json['controls'] ?? {}),
      compute: ComputeData.fromJson(json['compute'] ?? {}),
      autonomy: AutonomyData.fromJson(json['autonomy'] ?? {}),
      sensors: (json['sensors'] as List<dynamic>?)
              ?.map((s) => SensorHealth.fromJson(s))
              .toList() ??
          [],
      simulation: json['simulation'] != null
          ? SimulationData.fromJson(json['simulation'])
          : null,
    );
  }
}

class LocationData {
  final double latitude;
  final double longitude;
  final double altitude;
  final double heading;

  LocationData({
    required this.latitude,
    required this.longitude,
    required this.altitude,
    required this.heading,
  });

  factory LocationData.fromJson(Map<String, dynamic> json) {
    return LocationData(
      latitude: (json['latitude'] as num?)?.toDouble() ?? 0.0,
      longitude: (json['longitude'] as num?)?.toDouble() ?? 0.0,
      altitude: (json['altitude'] as num?)?.toDouble() ?? 0.0,
      heading: (json['heading'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class KinematicsData {
  final double speed;
  final double speedKmh;
  final double acceleration;
  final double yawRate;
  final double roll;
  final double pitch;

  KinematicsData({
    required this.speed,
    required this.speedKmh,
    required this.acceleration,
    required this.yawRate,
    required this.roll,
    required this.pitch,
  });

  factory KinematicsData.fromJson(Map<String, dynamic> json) {
    return KinematicsData(
      speed: (json['speed'] as num?)?.toDouble() ?? 0.0,
      speedKmh: (json['speed_kmh'] as num?)?.toDouble() ?? 0.0,
      acceleration: (json['acceleration'] as num?)?.toDouble() ?? 0.0,
      yawRate: (json['yaw_rate'] as num?)?.toDouble() ?? 0.0,
      roll: (json['roll'] as num?)?.toDouble() ?? 0.0,
      pitch: (json['pitch'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class ControlsData {
  final double steering;
  final double throttle;
  final double brake;
  final String gear;
  final bool handbrake;
  final String turnIndicator;

  ControlsData({
    required this.steering,
    required this.throttle,
    required this.brake,
    required this.gear,
    required this.handbrake,
    required this.turnIndicator,
  });

  factory ControlsData.fromJson(Map<String, dynamic> json) {
    return ControlsData(
      steering: (json['steering'] as num?)?.toDouble() ?? 0.0,
      throttle: (json['throttle'] as num?)?.toDouble() ?? 0.0,
      brake: (json['brake'] as num?)?.toDouble() ?? 0.0,
      gear: json['gear'] ?? 'D',
      handbrake: json['handbrake'] ?? false,
      turnIndicator: json['turn_indicator'] ?? 'OFF',
    );
  }
}

class ComputeData {
  final double cpuUsage;
  final double gpuUsage;
  final double memoryUsage;
  final double temperatureC;

  ComputeData({
    required this.cpuUsage,
    required this.gpuUsage,
    required this.memoryUsage,
    required this.temperatureC,
  });

  factory ComputeData.fromJson(Map<String, dynamic> json) {
    return ComputeData(
      cpuUsage: (json['cpu_usage'] as num?)?.toDouble() ?? 0.0,
      gpuUsage: (json['gpu_usage'] as num?)?.toDouble() ?? 0.0,
      memoryUsage: (json['memory_usage'] as num?)?.toDouble() ?? 0.0,
      temperatureC: (json['temperature_c'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class AutonomyData {
  final String mode;
  final String status;
  final String? disengagementReason;
  final double targetSpeedKmh;
  final double cteMeters;

  AutonomyData({
    required this.mode,
    required this.status,
    this.disengagementReason,
    required this.targetSpeedKmh,
    required this.cteMeters,
  });

  factory AutonomyData.fromJson(Map<String, dynamic> json) {
    return AutonomyData(
      mode: json['mode'] ?? 'MANUAL',
      status: json['status'] ?? 'STANDBY',
      disengagementReason: json['disengagement_reason'],
      targetSpeedKmh: (json['target_speed_kmh'] as num?)?.toDouble() ?? 0.0,
      cteMeters: (json['cte_meters'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class SensorHealth {
  final String name;
  final String sensorType;
  final String status;
  final double fps;
  final double latencyMs;

  SensorHealth({
    required this.name,
    required this.sensorType,
    required this.status,
    required this.fps,
    required this.latencyMs,
  });

  factory SensorHealth.fromJson(Map<String, dynamic> json) {
    return SensorHealth(
      name: json['name'] ?? '',
      sensorType: json['sensor_type'] ?? '',
      status: json['status'] ?? 'ONLINE',
      fps: (json['fps'] as num?)?.toDouble() ?? 0.0,
      latencyMs: (json['latency_ms'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class SimulationData {
  final bool isSimulated;
  final String simulator;
  final String scenario;
  final String weather;
  final double timeOfDay;
  final double simulationFps;

  SimulationData({
    required this.isSimulated,
    required this.simulator,
    required this.scenario,
    required this.weather,
    required this.timeOfDay,
    required this.simulationFps,
  });

  factory SimulationData.fromJson(Map<String, dynamic> json) {
    return SimulationData(
      isSimulated: json['is_simulated'] ?? false,
      simulator: json['simulator'] ?? 'CARLA',
      scenario: json['scenario'] ?? 'Town01',
      weather: json['weather'] ?? 'ClearNoon',
      timeOfDay: (json['time_of_day'] as num?)?.toDouble() ?? 12.0,
      simulationFps: (json['simulation_fps'] as num?)?.toDouble() ?? 30.0,
    );
  }
}
