import 'dart:math';
import 'package:flutter/material.dart';

class GaugeSpeedometer extends StatelessWidget {
  final double speedKmh;
  final double targetSpeedKmh;
  final String gear;

  const GaugeSpeedometer({
    Key? key,
    required this.speedKmh,
    this.targetSpeedKmh = 50.0,
    this.gear = 'D',
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    final speedMph = (speedKmh * 0.621371).round();

    return Container(
      width: 260,
      height: 260,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: const Color(0xFF0F172A), // Slate 900
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF06B6D4).withOpacity(0.15), // Cyan glow
            blurRadius: 24,
            spreadRadius: 4,
          ),
        ],
        border: Border.all(color: const Color(0xFF1E293B), width: 2),
      ),
      child: Stack(
        alignment: Alignment.center,
        children: [
          CustomPaint(
            size: const Size(220, 220),
            painter: _SpeedGaugePainter(
              speed: speedKmh,
              maxSpeed: 140.0,
            ),
          ),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Gear Badge
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
                decoration: BoxDecoration(
                  color: const Color(0xFF1E293B),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: const Color(0xFF334155)),
                ),
                child: Text(
                  gear,
                  style: const TextStyle(
                    color: Color(0xFF38BDF8),
                    fontSize: 18,
                    fontWeight: FontWeight.w900,
                    letterSpacing: 2,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              // Speed Number
              Text(
                speedKmh.round().toString(),
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 54,
                  fontWeight: FontWeight.bold,
                  height: 1.0,
                  letterSpacing: -1,
                ),
              ),
              const Text(
                'KM/H',
                style: TextStyle(
                  color: Color(0xFF94A3B8),
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 1.5,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '$speedMph MPH',
                style: const TextStyle(
                  color: Color(0xFF64748B),
                  fontSize: 11,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SpeedGaugePainter extends CustomPainter {
  final double speed;
  final double maxSpeed;

  _SpeedGaugePainter({required this.speed, required this.maxSpeed});

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2 - 12;

    const startAngle = 135.0 * (pi / 180.0);
    const sweepAngle = 270.0 * (pi / 180.0);

    // Track Paint
    final trackPaint = Paint()
      ..color = const Color(0xFF1E293B)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 12
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      startAngle,
      sweepAngle,
      false,
      trackPaint,
    );

    // Progress Arc Paint
    final progressFraction = (speed / maxSpeed).clamp(0.0, 1.0);
    final progressSweep = sweepAngle * progressFraction;

    Color arcColor = const Color(0xFF06B6D4); // Cyan
    if (speed > 80.0) {
      arcColor = const Color(0xFFF59E0B); // Amber
    }
    if (speed > 110.0) {
      arcColor = const Color(0xFFEF4444); // Red
    }

    final progressPaint = Paint()
      ..shader = SweepGradient(
        colors: [const Color(0xFF06B6D4), arcColor],
        startAngle: startAngle,
        endAngle: startAngle + sweepAngle,
      ).createShader(Rect.fromCircle(center: center, radius: radius))
      ..style = PaintingStyle.stroke
      ..strokeWidth = 12
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      startAngle,
      progressSweep,
      false,
      progressPaint,
    );
  }

  @override
  bool shouldRepaint(covariant _SpeedGaugePainter oldDelegate) {
    return oldDelegate.speed != speed;
  }
}
