import 'package:dio/dio.dart';
import 'api_client.dart';

class NotificationService {
  final Dio _dio;

  NotificationService({Dio? dio}) : _dio = dio ?? createDio();

  // ── Events ──────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> ingestEvent({
    required String eventType,
    required Map<String, dynamic> payload,
    String? idempotencyKey,
  }) async {
    final response = await _dio.post('/events/ingest', data: {
      'event_type': eventType,
      'payload': payload,
      if (idempotencyKey != null) 'idempotency_key': idempotencyKey,
    });
    return response.data as Map<String, dynamic>;
  }

  // ── Rules ────────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getRules({
    int skip = 0,
    int limit = 50,
    bool? activeOnly,
  }) async {
    final response = await _dio.get('/rules', queryParameters: {
      'skip': skip,
      'limit': limit,
      if (activeOnly != null) 'active_only': activeOnly,
    });
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createRule(Map<String, dynamic> data) async {
    final response = await _dio.post('/rules', data: data);
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateRule(
      String id, Map<String, dynamic> data) async {
    final response = await _dio.patch('/rules/$id', data: data);
    return response.data as Map<String, dynamic>;
  }

  Future<void> deleteRule(String id) async {
    await _dio.delete('/rules/$id');
  }

  // ── Templates ────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getTemplates({
    int skip = 0,
    int limit = 50,
    String? channelId,
    String? language,
  }) async {
    final response = await _dio.get('/templates', queryParameters: {
      'skip': skip,
      'limit': limit,
      if (channelId != null) 'channel_id': channelId,
      if (language != null) 'language': language,
    });
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createTemplate(
      Map<String, dynamic> data) async {
    final response = await _dio.post('/templates', data: data);
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateTemplate(
      String id, Map<String, dynamic> data) async {
    final response = await _dio.patch('/templates/$id', data: data);
    return response.data as Map<String, dynamic>;
  }

  Future<void> deleteTemplate(String id) async {
    await _dio.delete('/templates/$id');
  }

  // ── Channels ─────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getChannels() async {
    final response = await _dio.get('/channels');
    return response.data as Map<String, dynamic>;
  }

  // ── Logs ─────────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getDeliveryLogs({
    int skip = 0,
    int limit = 50,
    String? eventType,
    String? channel,
    String? status,
  }) async {
    final response = await _dio.get('/logs', queryParameters: {
      'skip': skip,
      'limit': limit,
      if (eventType != null) 'event_type': eventType,
      if (channel != null) 'channel': channel,
      if (status != null) 'status': status,
    });
    return response.data as Map<String, dynamic>;
  }

  // ── Preferences ───────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getMyPreferences() async {
    final response = await _dio.get('/preferences/me');
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> upsertMyPreference(
      String channelId, Map<String, dynamic> data) async {
    final response = await _dio.put('/preferences/me/$channelId', data: data);
    return response.data as Map<String, dynamic>;
  }

  // ── Company Settings ──────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getCompanySettings() async {
    final response = await _dio.get('/company-settings/me');
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> updateCompanySettings(
      Map<String, dynamic> data) async {
    final response = await _dio.patch('/company-settings/me', data: data);
    return response.data as Map<String, dynamic>;
  }

  // ── API Keys ──────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getApiKeys() async {
    final response = await _dio.get('/api-keys');
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createApiKey(Map<String, dynamic> data) async {
    final response = await _dio.post('/api-keys', data: data);
    return response.data as Map<String, dynamic>;
  }

  Future<void> revokeApiKey(String id) async {
    await _dio.delete('/api-keys/$id');
  }

  // ── Webhooks ──────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> getWebhooks() async {
    final response = await _dio.get('/webhooks');
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> createWebhook(
      Map<String, dynamic> data) async {
    final response = await _dio.post('/webhooks', data: data);
    return response.data as Map<String, dynamic>;
  }

  Future<void> deleteWebhook(String id) async {
    await _dio.delete('/webhooks/$id');
  }
}
