import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../api/notification_service.dart';

final notificationServiceProvider = Provider<NotificationService>((ref) {
  return NotificationService();
});

// ── Delivery Logs ──────────────────────────────────────────────────────────

/// Query key for [deliveryLogsProvider].
///
/// Pre-existing bug fix: this family used to be keyed by a `Map`, and the
/// screens watched it with a fresh map literal on every build. Maps have no
/// value equality, so each rebuild produced a "new" family key → a new request
/// → a rebuild → another new key … an infinite loop that hammered the API and
/// left every screen stuck on a spinner. A record has value equality, so equal
/// queries across rebuilds resolve to the same provider and fetch once.
typedef LogQuery = ({int skip, int limit, String? channel, String? status});

final deliveryLogsProvider = FutureProvider.family<Map<String, dynamic>, LogQuery>(
  (ref, q) async {
    final service = ref.watch(notificationServiceProvider);
    return service.getDeliveryLogs(
      skip: q.skip,
      limit: q.limit,
      channel: q.channel,
      status: q.status,
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

// ── Integrations ─────────────────────────────────────────────────────────────

final integrationCatalogProvider = FutureProvider<List<dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getIntegrationCatalog();
});

/// Connected state is JWT-admin only; callers tolerate an error by treating it
/// as "no connectors connected".
final connectorStatusProvider = FutureProvider<List<dynamic>>((ref) async {
  final service = ref.watch(notificationServiceProvider);
  return service.getConnectorStatus();
});
