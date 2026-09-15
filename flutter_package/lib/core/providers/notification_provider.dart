import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../api/notification_service.dart';

final notificationServiceProvider = Provider<NotificationService>((ref) {
  return NotificationService();
});

// ── Delivery Logs ──────────────────────────────────────────────────────────

final deliveryLogsProvider = FutureProvider.family<Map<String, dynamic>, Map<String, dynamic>>(
  (ref, params) async {
    final service = ref.watch(notificationServiceProvider);
    return service.getDeliveryLogs(
      skip: params['skip'] ?? 0,
      limit: params['limit'] ?? 50,
      channel: params['channel'],
      status: params['status'],
    );
  },
);

// ── Rules ──────────────────────────────────────────────────────────────────

final rulesProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getRules();
});

// ── Templates ──────────────────────────────────────────────────────────────

final templatesProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getTemplates();
});

// ── Channels ───────────────────────────────────────────────────────────────

final channelsProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getChannels();
});

// ── Company Settings ───────────────────────────────────────────────────────

final companySettingsProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getCompanySettings();
});

// ── My Preferences ─────────────────────────────────────────────────────────

final myPreferencesProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getMyPreferences();
});

// ── API Keys ───────────────────────────────────────────────────────────────

final apiKeysProvider = FutureProvider<Map<String, dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getApiKeys();
});
