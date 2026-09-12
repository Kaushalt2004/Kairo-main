import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/telemetry_model.dart';

class KairoWsService extends ChangeNotifier {
  final String cloudBaseUrl; // e.g. "http://localhost:8000"
  final String cloudWsUrl;   // e.g. "ws://localhost:8000"
  final String vehicleId;
  final String? authToken;

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _reconnectTimer;
  Timer? _pingTimer;

  bool _isConnected = false;
  String _connectionStatus = 'Disconnected';
  TelemetryModel? _latestTelemetry;
  String? _lastCommandStatus;

  KairoWsService({
    this.cloudBaseUrl = 'http://localhost:8000',
    this.cloudWsUrl = 'ws://localhost:8000',
    this.vehicleId = 'KAIRO-001',
    this.authToken,
  });

  bool get isConnected => _isConnected;
  String get connectionStatus => _connectionStatus;
  TelemetryModel? get latestTelemetry => _latestTelemetry;
  String? get lastCommandStatus => _lastCommandStatus;

  void connect() {
    _reconnectTimer?.cancel();
    _connectionStatus = 'Connecting...';
    notifyListeners();

    try {
      final uri = Uri.parse('$cloudWsUrl/ws/v1/stream/telemetry?vehicle_id=$vehicleId');
      _channel = WebSocketChannel.connect(uri);

      _subscription = _channel!.stream.listen(
        (message) {
          _handleMessage(message);
        },
        onDone: () {
          _onDisconnected('Stream closed');
        },
        onError: (error) {
          _onDisconnected('Connection error: $error');
        },
        cancelOnError: true,
      );

      _isConnected = true;
      _connectionStatus = 'Connected to $vehicleId';
      notifyListeners();

      // Start ping loop
      _pingTimer?.cancel();
      _pingTimer = Timer.periodic(const Duration(seconds: 15), (timer) {
        if (_isConnected && _channel != null) {
          _channel!.sink.add(jsonEncode({'type': 'ping'}));
        }
      });
    } catch (e) {
      _onDisconnected('Failed to connect: $e');
    }
  }

  void _handleMessage(dynamic raw) {
    try {
      final Map<String, dynamic> msg = jsonDecode(raw.toString());
      final type = msg['type'];

      if (type == 'telemetry') {
        final data = msg['data'];
        if (data != null) {
          _latestTelemetry = TelemetryModel.fromJson(data);
          notifyListeners();
        }
      } else if (type == 'command_update') {
        final status = msg['data']?['status'] ?? 'UPDATED';
        _lastCommandStatus = status;
        notifyListeners();
      }
    } catch (e) {
      debugPrint('Error decoding telemetry frame: $e');
    }
  }

  void _onDisconnected(String reason) {
    _isConnected = false;
    _connectionStatus = reason;
    _channel = null;
    _pingTimer?.cancel();
    notifyListeners();

    // Reconnect after 3 seconds
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), () {
      connect();
    });
  }

  Future<bool> sendCommand(String commandType, Map<String, dynamic> parameters) async {
    try {
      final url = Uri.parse('$cloudBaseUrl/api/v1/commands/$vehicleId');
      final headers = {
        'Content-Type': 'application/json',
        if (authToken != null) 'Authorization': 'Bearer $authToken',
      };
      final body = jsonEncode({
        'command_type': commandType,
        'parameters': parameters,
      });

      final response = await http.post(url, headers: headers, body: body);
      if (response.statusCode == 200 || response.statusCode == 202) {
        _lastCommandStatus = 'DISPATCHED: $commandType';
        notifyListeners();
        return true;
      } else {
        _lastCommandStatus = 'FAILED: ${response.body}';
        notifyListeners();
        return false;
      }
    } catch (e) {
      _lastCommandStatus = 'ERROR: $e';
      notifyListeners();
      return false;
    }
  }

  @override
  void dispose() {
    _reconnectTimer?.cancel();
    _pingTimer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    super.dispose();
  }
}
