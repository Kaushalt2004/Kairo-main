import 'package:flutter/material.dart';
import '../models/telemetry_model.dart';

class SensorStatusGrid extends StatelessWidget {
  final List<SensorHealth> sensors;

  const SensorStatusGrid({Key? key, required this.sensors}) : super(key: key);

  @override
  Widget build(BuildContext context) {
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
                'SENSOR PERCEPTION MATRIX',
                style: TextStyle(
                  color: Color(0xFF64748B),
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.2,
                ),
              ),
              Text(
                '${sensors.where((s) => s.status == 'ONLINE').length}/${sensors.length} ACTIVE',
                style: const TextStyle(
                  color: Color(0xFF10B981),
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: sensors.map((sensor) => _buildSensorBadge(sensor)).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildSensorBadge(SensorHealth sensor) {
    Color statusColor;
    switch (sensor.status.toUpperCase()) {
      case 'ONLINE':
        statusColor = const Color(0xFF10B981); // Emerald
        break;
      case 'DEGRADED':
        statusColor = const Color(0xFFF59E0B); // Amber
        break;
      default:
        statusColor = const Color(0xFFEF4444); // Red
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: statusColor.withOpacity(0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: statusColor,
              boxShadow: [
                BoxShadow(color: statusColor.withOpacity(0.6), blurRadius: 4),
              ],
            ),
          ),
          const SizedBox(width: 6),
          Text(
            sensor.name,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            '${sensor.fps.round()}Hz',
            style: const TextStyle(
              color: Color(0xFF94A3B8),
              fontSize: 10,
            ),
          ),
        ],
      ),
    );
  }
}
