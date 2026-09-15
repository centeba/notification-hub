import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/providers/notification_provider.dart';

/// Sensible default secret fields per api_key connector so the form isn't blank.
const Map<String, List<String>> _defaultFields = {
  's3': ['access_key_id', 'secret_access_key', 'region', 'bucket'],
  'stripe': ['api_key'],
  'mailchimp': ['api_key', 'server_prefix'],
  'datadog': ['api_key', 'app_key'],
  'splunk': ['hec_token', 'hec_url'],
  'grafana': ['api_key', 'base_url'],
  'elasticsearch': ['api_key', 'base_url'],
  'kibana': ['api_key', 'base_url'],
  'claude': ['api_key'],
};

String _authLabel(String auth) => switch (auth) {
      'oauth2' => 'OAuth',
      'api_key' => 'API key',
      _ => 'No auth',
    };

class IntegrationsScreen extends ConsumerWidget {
  const IntegrationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final catalogAsync = ref.watch(integrationCatalogProvider);
    // Connected state is admin-only and may 401/403; treat any error as "none".
    final statusList = ref.watch(connectorStatusProvider).asData?.value ?? const [];
    final statusByConnector = <String, Map<String, dynamic>>{};
    for (final s in statusList) {
      final m = s as Map<String, dynamic>;
      statusByConnector[m['connector'] as String] = m;
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Integrations')),
      body: catalogAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (entries) {
          if (entries.isEmpty) {
            return const Center(child: Text('No integrations available.'));
          }
          final byCategory = <String, List<Map<String, dynamic>>>{};
          for (final e in entries) {
            final m = e as Map<String, dynamic>;
            byCategory.putIfAbsent(m['category'] as String, () => []).add(m);
          }
          final categories = byCategory.keys.toList()..sort();

          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              const Padding(
                padding: EdgeInsets.only(bottom: 12),
                child: Text(
                  'Connect the notification hub to external services. OAuth '
                  'connectors open a consent screen; API-key connectors store '
                  'credentials securely for your company.',
                ),
              ),
              for (final category in categories) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 8, bottom: 4),
                  child: Text(
                    category.toUpperCase(),
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          letterSpacing: 0.6,
                          color: Theme.of(context).colorScheme.outline,
                        ),
                  ),
                ),
                for (final entry in byCategory[category]!)
                  _IntegrationCard(
                    entry: entry,
                    connected: statusByConnector[entry['key']],
                    onChanged: () {
                      ref.invalidate(integrationCatalogProvider);
                      ref.invalidate(connectorStatusProvider);
                    },
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _IntegrationCard extends ConsumerWidget {
  final Map<String, dynamic> entry;
  final Map<String, dynamic>? connected;
  final VoidCallback onChanged;

  const _IntegrationCard({
    required this.entry,
    required this.connected,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = entry['auth'] as String;
    final name = entry['name'] as String;
    final isConnected = connected != null;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    name,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (isConnected)
                  _Badge(label: 'Connected', color: Colors.green)
                else
                  _Badge(
                    label: _authLabel(auth),
                    color: Theme.of(context).colorScheme.outline,
                  ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              entry['description'] as String,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: _action(context, ref, auth, isConnected),
            ),
          ],
        ),
      ),
    );
  }

  Widget _action(
    BuildContext context,
    WidgetRef ref,
    String auth,
    bool isConnected,
  ) {
    if (isConnected) {
      return TextButton(
        style: TextButton.styleFrom(foregroundColor: Colors.red),
        onPressed: () => _disconnect(context, ref),
        child: const Text('Disconnect'),
      );
    }
    if (auth == 'none') {
      return Text(
        'No credentials required.',
        style: Theme.of(context).textTheme.bodySmall,
      );
    }
    if (auth == 'oauth2') {
      return FilledButton(
        onPressed: () => _startOauth(context, ref),
        child: const Text('Connect'),
      );
    }
    return FilledButton(
      onPressed: () => _showApiKeyForm(context, ref),
      child: const Text('Connect'),
    );
  }

  Future<void> _disconnect(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Disconnect ${entry['name']}?'),
        content: const Text('The stored credential will be removed.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final messenger = ScaffoldMessenger.of(context);
    final service = ref.read(notificationServiceProvider);
    try {
      await service.disconnectIntegration(connected!['credential_id'] as String);
      onChanged();
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Disconnect failed: $e')));
    }
  }

  Future<void> _startOauth(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    final service = ref.read(notificationServiceProvider);
    String url;
    try {
      url = await service.getOAuthAuthorizeUrl(
        entry['key'] as String,
        entry['name'] as String,
      );
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('Could not start OAuth: $e')));
      return;
    }
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Connect ${entry['name']}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Open this URL in your browser to grant access:'),
            const SizedBox(height: 8),
            SelectableText(url, style: const TextStyle(fontSize: 12)),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Clipboard.setData(ClipboardData(text: url));
              Navigator.pop(ctx);
            },
            child: const Text('Copy URL'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Done'),
          ),
        ],
      ),
    );
  }

  Future<void> _showApiKeyForm(BuildContext context, WidgetRef ref) async {
    final saved = await showDialog<bool>(
      context: context,
      builder: (_) => _ApiKeyDialog(entry: entry),
    );
    if (saved == true) onChanged();
  }
}

class _ApiKeyDialog extends ConsumerStatefulWidget {
  final Map<String, dynamic> entry;

  const _ApiKeyDialog({required this.entry});

  @override
  ConsumerState<_ApiKeyDialog> createState() => _ApiKeyDialogState();
}

class _ApiKeyDialogState extends ConsumerState<_ApiKeyDialog> {
  late final TextEditingController _name;
  late final List<_FieldRow> _fields;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.entry['name'] as String);
    final keys = _defaultFields[widget.entry['key']] ?? const ['api_key'];
    _fields = [for (final k in keys) _FieldRow(k)];
  }

  @override
  void dispose() {
    _name.dispose();
    for (final f in _fields) {
      f.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    final secretData = <String, dynamic>{};
    for (final f in _fields) {
      final key = f.key.text.trim();
      final value = f.value.text.trim();
      if (key.isNotEmpty && value.isNotEmpty) secretData[key] = value;
    }
    final messenger = ScaffoldMessenger.of(context);
    if (secretData.isEmpty) {
      messenger.showSnackBar(
        const SnackBar(content: Text('Enter at least one credential field.')),
      );
      return;
    }
    setState(() => _busy = true);
    final service = ref.read(notificationServiceProvider);
    try {
      await service.connectIntegration(
        connector: widget.entry['key'] as String,
        name: _name.text.trim().isEmpty
            ? widget.entry['name'] as String
            : _name.text.trim(),
        secretData: secretData,
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => _busy = false);
      messenger.showSnackBar(SnackBar(content: Text('Connect failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Connect ${widget.entry['name']}'),
      content: SizedBox(
        width: 360,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _name,
                decoration: const InputDecoration(labelText: 'Display name'),
              ),
              const SizedBox(height: 8),
              for (final f in _fields)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: f.key,
                          decoration: const InputDecoration(labelText: 'field'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: TextField(
                          controller: f.value,
                          obscureText: true,
                          decoration: const InputDecoration(labelText: 'value'),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: _fields.length == 1
                            ? null
                            : () => setState(() {
                                  f.dispose();
                                  _fields.remove(f);
                                }),
                      ),
                    ],
                  ),
                ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  icon: const Icon(Icons.add),
                  label: const Text('Add field'),
                  onPressed: () => setState(() => _fields.add(_FieldRow(''))),
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : () => Navigator.pop(context, false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: _busy ? null : _save,
          child: Text(_busy ? 'Saving…' : 'Save'),
        ),
      ],
    );
  }
}

class _FieldRow {
  final TextEditingController key;
  final TextEditingController value;

  _FieldRow(String initialKey)
      : key = TextEditingController(text: initialKey),
        value = TextEditingController();

  void dispose() {
    key.dispose();
    value.dispose();
  }
}

class _Badge extends StatelessWidget {
  final String label;
  final Color color;

  const _Badge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(label, style: TextStyle(fontSize: 11, color: color)),
    );
  }
}
