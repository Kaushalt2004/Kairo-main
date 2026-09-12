import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'screens/dashboard_screen.dart';
import 'services/kairo_ws_service.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Force landscape tablet orientation
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.landscapeLeft,
    DeviceOrientation.landscapeRight,
  ]);

  // Set system UI to immersive dark
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: Color(0xFF030712),
      systemNavigationBarIconBrightness: Brightness.light,
    ),
  );

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(
          create: (_) => KairoWsService(
            cloudBaseUrl: const String.fromEnvironment('KAIRO_CLOUD_URL', defaultValue: 'http://localhost:8000'),
            cloudWsUrl: const String.fromEnvironment('KAIRO_CLOUD_WS', defaultValue: 'ws://localhost:8000'),
            vehicleId: const String.fromEnvironment('KAIRO_VEHICLE_ID', defaultValue: 'KAIRO-001'),
          ),
        ),
      ],
      child: const KairoTabletApp(),
    ),
  );
}

class KairoTabletApp extends StatelessWidget {
  const KairoTabletApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Kairo Autonomous HMI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF030712),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF06B6D4),
          secondary: Color(0xFF38BDF8),
          surface: Color(0xFF0F172A),
          background: Color(0xFF030712),
        ),
        fontFamily: 'Inter',
      ),
      home: const DashboardScreen(),
    );
  }
}
