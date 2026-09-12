import 'package:flutter/material.dart';
import '../models/telemetry_model.dart';

class ComputeCard extends StatelessWidget {
  final ComputeData compute;

  const ComputeCard({Key? key, required this.compute}) : super(key: key);

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
                'ONBOARD COMPUTE (IPC / GPU)',
                style: TextStyle(
                  color: Color(0xFF64748B),
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.2,
                ),
              ),
              Row(
                children: [
                  const Icon(Icons.thermostat, color: Color(0xFFF97316), size: 16),
                  const SizedBox(width: 2),
                  Text(
                    '${compute.temperatureC.round()}°C',
                    style: const TextStyle(
                      color: Color(0xFFF97316),
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: _buildMetricItem('CPU', compute.cpuUsage, const Color(0xFF38BDF8))),
              const SizedBox(width: 12),
              Expanded(child: _buildMetricItem('GPU', compute.gpuUsage, const Color(0xFFA855F7))),
              const SizedBox(width: 12),
              Expanded(child: _buildMetricItem('RAM', compute.memoryUsage, const Color(0xFF10B981))),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildMetricItem(String label, double value, Color color) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        children: [
          Text(
            label,
            style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 10, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 4),
          Text(
            '${value.round()}%',
            style: TextStyle(color: color, fontSize: 16, fontWeight: FontWeight.bold),
          ),
        ],
      ),
    );
  }
}
