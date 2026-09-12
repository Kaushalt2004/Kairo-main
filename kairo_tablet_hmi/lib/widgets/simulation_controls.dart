import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/kairo_ws_service.dart';

class SimulationControls extends StatelessWidget {
  final String currentMode;

  const SimulationControls({Key? key, required this.currentMode}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    final wsService = Provider.of<KairoWsService>(context, listen: false);

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
            'MISSION & AUTONOMY DISPATCH',
            style: TextStyle(
              color: Color(0xFF64748B),
              fontSize: 11,
              fontWeight: FontWeight.bold,
              letterSpacing: 1.2,
            ),
          ),
          const SizedBox(height: 12),
          // Autonomy Mode Selectors
          Row(
            children: [
              Expanded(
                child: _buildModeButton(
                  context: context,
                  label: 'MANUAL',
                  mode: 'MANUAL',
                  activeColor: const Color(0xFF64748B),
                  onTap: () => wsService.sendCommand('SET_AUTONOMY_MODE', {'mode': 'MANUAL'}),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _buildModeButton(
                  context: context,
                  label: 'ASSISTED',
                  mode: 'ASSISTED',
                  activeColor: const Color(0xFF38BDF8),
                  onTap: () => wsService.sendCommand('SET_AUTONOMY_MODE', {'mode': 'ASSISTED'}),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _buildModeButton(
                  context: context,
                  label: 'AUTO DRIVE',
                  mode: 'AUTONOMOUS',
                  activeColor: const Color(0xFF10B981),
                  onTap: () => wsService.sendCommand('SET_AUTONOMY_MODE', {'mode': 'AUTONOMOUS'}),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Simulation Quick Commands
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  icon: const Icon(Icons.play_arrow, size: 16),
                  label: const Text('START SIM', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF0284C7),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  onPressed: () => wsService.sendCommand('START_SIMULATION', {'scenario': 'Town01_Standard'}),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: ElevatedButton.icon(
                  icon: const Icon(Icons.stop, size: 16),
                  label: const Text('STOP SIM', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF334155),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  onPressed: () => wsService.sendCommand('STOP_SIMULATION', {}),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: ElevatedButton.icon(
                  icon: const Icon(Icons.cloud, size: 16),
                  label: const Text('RAIN', style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF1E293B),
                    foregroundColor: const Color(0xFF38BDF8),
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                      side: const BorderSide(color: Color(0xFF0284C7)),
                    ),
                  ),
                  onPressed: () => wsService.sendCommand('CHANGE_WEATHER', {'weather': 'HardRainNoon'}),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Big Emergency Stop Button
          SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              icon: const Icon(Icons.warning_amber_rounded, size: 20),
              label: const Text(
                'EMERGENCY STOP (E-STOP)',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w900, letterSpacing: 1.5),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFDC2626), // Crimson Red
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                elevation: 6,
                shadowColor: const Color(0xFFEF4444).withOpacity(0.5),
              ),
              onPressed: () => wsService.sendCommand('SET_AUTONOMY_MODE', {'mode': 'EMERGENCY_STOP'}),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildModeButton({
    required BuildContext context,
    required String label,
    required String mode,
    required Color activeColor,
    required VoidCallback onTap,
  }) {
    final isSelected = currentMode.toUpperCase() == mode.toUpperCase();
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          color: isSelected ? activeColor.withOpacity(0.2) : const Color(0xFF1E293B),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: isSelected ? activeColor : const Color(0xFF334155),
            width: isSelected ? 2 : 1,
          ),
        ),
        child: Center(
          child: Text(
            label,
            style: TextStyle(
              color: isSelected ? activeColor : const Color(0xFF94A3B8),
              fontSize: 11,
              fontWeight: FontWeight.bold,
              letterSpacing: 1.0,
            ),
          ),
        ),
      ),
    );
  }
}
