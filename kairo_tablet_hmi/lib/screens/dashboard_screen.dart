import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/telemetry_model.dart';
import '../services/kairo_ws_service.dart';
import '../widgets/compute_card.dart';
import '../widgets/control_inputs_bar.dart';
import '../widgets/gauge_speedometer.dart';
import '../widgets/sensor_status_grid.dart';
import '../widgets/simulation_controls.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({Key? key}) : super(key: key);

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  @override
  void initState() {
    super.initState();
    // Connect WebSocket stream on mount
    WidgetsBinding.instance.addPostFrameCallback((_) {
      Provider.of<KairoWsService>(context, listen: false).connect();
    });
  }

  @override
  Widget build(BuildContext context) {
    final wsService = Provider.of<KairoWsService>(context);
    final telemetry = wsService.latestTelemetry;

    return Scaffold(
      backgroundColor: const Color(0xFF030712), // Deep Obsidian
      body: SafeArea(
        child: Column(
          children: [
            // Top Header Bar
            _buildTopBar(wsService, telemetry),
            // Main Dashboard Body
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Left Column: Primary Driving Dynamics
                    SizedBox(
                      width: 320,
                      child: SingleChildScrollView(
                        child: Column(
                          children: [
                            GaugeSpeedometer(
                              speedKmh: telemetry?.kinematics.speedKmh ?? 0.0,
                              targetSpeedKmh: telemetry?.autonomy.targetSpeedKmh ?? 50.0,
                              gear: telemetry?.controls.gear ?? 'D',
                            ),
                            const SizedBox(height: 16),
                            ControlInputsBar(
                              throttle: telemetry?.controls.throttle ?? 0.0,
                              brake: telemetry?.controls.brake ?? 0.0,
                              steering: telemetry?.controls.steering ?? 0.0,
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(width: 16),

                    // Middle Column: Spatial Navigation / Scenario State
                    Expanded(
                      flex: 4,
                      child: Column(
                        children: [
                          Expanded(
                            child: _buildNavigationCard(telemetry),
                          ),
                          const SizedBox(height: 12),
                          SensorStatusGrid(sensors: telemetry?.sensors ?? []),
                        ],
                      ),
                    ),
                    const SizedBox(width: 16),

                    // Right Column: Compute telemetry & Mission Controls
                    SizedBox(
                      width: 340,
                      child: SingleChildScrollView(
                        child: Column(
                          children: [
                            SimulationControls(
                              currentMode: telemetry?.autonomy.mode ?? 'MANUAL',
                            ),
                            const SizedBox(height: 16),
                            ComputeCard(
                              compute: telemetry?.compute ??
                                  ComputeData(
                                    cpuUsage: 0.0,
                                    gpuUsage: 0.0,
                                    memoryUsage: 0.0,
                                    temperatureC: 0.0,
                                  ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTopBar(KairoWsService wsService, TelemetryModel? telemetry) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      decoration: const BoxDecoration(
        color: Color(0xFF0B1120),
        border: Border(bottom: BorderSide(color: Color(0xFF1E293B))),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: const Color(0xFF0284C7).withOpacity(0.2),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(Icons.directions_car, color: Color(0xFF38BDF8), size: 20),
              ),
              const SizedBox(width: 12),
              Text(
                'KAIRO // ${wsService.vehicleId}',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 1.5,
                ),
              ),
              const SizedBox(width: 12),
              // Connection Status Badge
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: wsService.isConnected
                      ? const Color(0xFF10B981).withOpacity(0.15)
                      : const Color(0xFFEF4444).withOpacity(0.15),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: wsService.isConnected ? const Color(0xFF10B981) : const Color(0xFFEF4444),
                  ),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 6,
                      height: 6,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: wsService.isConnected ? const Color(0xFF10B981) : const Color(0xFFEF4444),
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      wsService.isConnected ? 'CLOUD LIVE' : 'OFFLINE',
                      style: TextStyle(
                        color: wsService.isConnected ? const Color(0xFF10B981) : const Color(0xFFEF4444),
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          // GNSS Coordinates & Disengagement Mode
          Row(
            children: [
              if (telemetry != null) ...[
                Text(
                  'LAT: ${telemetry.location.latitude.toStringAsFixed(5)}  LON: ${telemetry.location.longitude.toStringAsFixed(5)}  ALT: ${telemetry.location.altitude.toStringAsFixed(1)}m',
                  style: const TextStyle(
                    color: Color(0xFF64748B),
                    fontFamily: 'monospace',
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                const SizedBox(width: 20),
              ],
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: const Color(0xFF1E293B),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  telemetry?.autonomy.mode ?? 'STANDBY',
                  style: const TextStyle(
                    color: Color(0xFF38BDF8),
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.0,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildNavigationCard(TelemetryModel? telemetry) {
    final heading = telemetry?.location.heading ?? 0.0;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF0F172A),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFF1E293B)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'BIRD\'S-EYE NAVIGATION & TRAJECTORY',
                style: TextStyle(
                  color: Color(0xFF64748B),
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.2,
                ),
              ),
              Text(
                'HEADING: ${heading.round()}°',
                style: const TextStyle(
                  color: Color(0xFF38BDF8),
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: const Color(0xFF030712),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF1E293B)),
              ),
              child: Stack(
                alignment: Alignment.center,
                children: [
                  // Grid Lines
                  CustomPaint(
                    size: Size.infinite,
                    painter: _GridPainter(),
                  ),
                  // Vehicle Icon & Heading Pointer
                  Transform.rotate(
                    angle: (heading * 3.14159 / 180.0),
                    child: Container(
                      width: 50,
                      height: 80,
                      decoration: BoxDecoration(
                        color: const Color(0xFF0284C7).withOpacity(0.3),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: const Color(0xFF38BDF8), width: 2),
                        boxShadow: [
                          BoxShadow(
                            color: const Color(0xFF38BDF8).withOpacity(0.4),
                            blurRadius: 16,
                          ),
                        ],
                      ),
                      child: const Center(
                        child: Icon(Icons.navigation, color: Color(0xFF38BDF8), size: 30),
                      ),
                    ),
                  ),
                  Positioned(
                    bottom: 12,
                    left: 12,
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: const Color(0xFF0F172A).withOpacity(0.85),
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: const Color(0xFF334155)),
                      ),
                      child: Text(
                        'SIMULATOR: ${telemetry?.simulation?.simulator ?? "CARLA"}  •  ${telemetry?.simulation?.scenario ?? "Town01"}  •  ${telemetry?.simulation?.weather ?? "ClearNoon"}',
                        style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 10, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _GridPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFF1E293B).withOpacity(0.5)
      ..strokeWidth = 1;

    const step = 40.0;
    for (double x = 0; x < size.width; x += step) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (double y = 0; y < size.height; y += step) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
