import 'dart:math';
import 'package:flutter/material.dart';

class ControlInputsBar extends StatelessWidget {
  final double throttle; // 0.0 to 1.0
  final double brake;    // 0.0 to 1.0
  final double steering; // -1.0 to 1.0

  const ControlInputsBar({
    Key? key,
    required this.throttle,
    required this.brake,
    required this.steering,
  }) : super(key: key);

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
          const Text(
            'ACTUATOR CONTROLS',
            style: TextStyle(
              color: Color(0xFF64748B),
              fontSize: 11,
              fontWeight: FontWeight.bold,
              letterSpacing: 1.2,
            ),
          ),
          const SizedBox(height: 12),
          // Throttle & Brake Bars
          Row(
            children: [
              Expanded(
                child: _buildBar(
                  label: 'THROTTLE',
                  value: throttle,
                  color: const Color(0xFF10B981), // Emerald
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: _buildBar(
                  label: 'BRAKE',
                  value: brake,
                  color: const Color(0xFFEF4444), // Rose Red
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          // Steering Angle
          _buildSteeringIndicator(),
        ],
      ),
    );
  }

  Widget _buildBar({required String label, required double value, required Color color}) {
    final pct = (value * 100).round();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              label,
              style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11, fontWeight: FontWeight.w600),
            ),
            Text(
              '$pct%',
              style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.bold),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(
            value: value.clamp(0.0, 1.0),
            minHeight: 10,
            backgroundColor: const Color(0xFF1E293B),
            valueColor: AlwaysStoppedAnimation<Color>(color),
          ),
        ),
      ],
    );
  }

  Widget _buildSteeringIndicator() {
    final deg = (steering * 450.0).round(); // Normalized to steering wheel degrees
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'STEERING WHEEL',
              style: TextStyle(color: Color(0xFF94A3B8), fontSize: 11, fontWeight: FontWeight.w600),
            ),
            Text(
              '$deg°',
              style: const TextStyle(color: Color(0xFF38BDF8), fontSize: 12, fontWeight: FontWeight.bold),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Center(
          child: Transform.rotate(
            angle: steering * (pi / 2),
            child: const Icon(
              Icons.radio_button_checked,
              color: Color(0xFF38BDF8),
              size: 32,
            ),
          ),
        ),
      ],
    );
  }
}
