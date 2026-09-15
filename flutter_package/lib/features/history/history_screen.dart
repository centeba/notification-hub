import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/providers/notification_provider.dart';
import '../../core/theme/app_colors.dart';

class HistoryScreen extends ConsumerStatefulWidget {
  const HistoryScreen({super.key});

  @override
  ConsumerState<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends ConsumerState<HistoryScreen> {
  String? _statusFilter;
  String? _channelFilter;

  @override
  Widget build(BuildContext context) {
    final logsAsync = ref.watch(deliveryLogsProvider({
      'limit': 50,
      if (_statusFilter != null) 'status': _statusFilter,
      if (_channelFilter != null) 'channel': _channelFilter,
    }));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Delivery History'),
        actions: [
          IconButton(
            icon: const Icon(Icons.filter_list),
            onPressed: _showFilters,
          ),
        ],
      ),
      body: Column(
        children: [
          // ── Active filters chip row ─────────────────────────────────
          if (_statusFilter != null || _channelFilter != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Row(
                children: [
                  if (_statusFilter != null)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: FilterChip(
                        label: Text('Status: $_statusFilter'),
                        selected: true,
                        onSelected: (_) => setState(() => _statusFilter = null),
                        deleteIcon: const Icon(Icons.close, size: 16),
                        onDeleted: () => setState(() => _statusFilter = null),
                      ),
                    ),
                  if (_channelFilter != null)
                    FilterChip(
                      label: Text('Channel: $_channelFilter'),
                      selected: true,
                      onSelected: (_) => setState(() => _channelFilter = null),
                      deleteIcon: const Icon(Icons.close, size: 16),
                      onDeleted: () => setState(() => _channelFilter = null),
                    ),
                ],
              ),
            ),
          // ── Log list ────────────────────────────────────────────────
          Expanded(
            child: logsAsync.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(child: Text('Error: $e')),
              data: (data) {
                final logs = (data['data'] as List?) ?? [];
                final count = data['count'] as int? ?? 0;
                if (logs.isEmpty) {
                  return const Center(child: Text('No delivery records found.'));
                }
                return Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                      child: Row(
                        children: [
                          Text('$count records', style: TextStyle(color: AppThemeColors.of(context).textMuted)),
                        ],
                      ),
                    ),
                    Expanded(
                      child: ListView.separated(
                        padding: const EdgeInsets.symmetric(horizontal: 16),
                        itemCount: logs.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (context, i) => _LogRow(log: logs[i] as Map<String, dynamic>),
                      ),
                    ),
                  ],
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  void _showFilters() {
    showModalBottomSheet(
      context: context,
      builder: (_) => Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Filter by Status', style: Theme.of(context).textTheme.titleMedium),
            Wrap(
              spacing: 8,
              children: ['sent', 'failed', 'pending', 'bounced'].map((s) {
                return ChoiceChip(
                  label: Text(s),
                  selected: _statusFilter == s,
                  onSelected: (val) {
                    setState(() => _statusFilter = val ? s : null);
                    Navigator.pop(context);
                  },
                );
              }).toList(),
            ),
            const SizedBox(height: 16),
            Text('Filter by Channel', style: Theme.of(context).textTheme.titleMedium),
            Wrap(
              spacing: 8,
              children: ['email', 'sms', 'webhook'].map((c) {
                return ChoiceChip(
                  label: Text(c),
                  selected: _channelFilter == c,
                  onSelected: (val) {
                    setState(() => _channelFilter = val ? c : null);
                    Navigator.pop(context);
                  },
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }
}

class _LogRow extends StatelessWidget {
  final Map<String, dynamic> log;

  const _LogRow({required this.log});

  @override
  Widget build(BuildContext context) {
    final status = log['status'] as String? ?? 'unknown';
    final statusColor = context.statusColor(status);
    final channelIcons = {'email': Icons.email, 'sms': Icons.sms, 'webhook': Icons.webhook};
    final channel = log['channel'] as String? ?? '';

    return ListTile(
      leading: Icon(channelIcons[channel] ?? Icons.notifications, color: AppThemeColors.of(context).textMuted),
      title: Text(log['event_type'] as String? ?? 'Unknown'),
      subtitle: Text(log['created_at'] as String? ?? ''),
      trailing: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: statusColor.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(
          status,
          style: TextStyle(color: statusColor, fontSize: 12, fontWeight: FontWeight.bold),
        ),
      ),
      onTap: () => _showDetails(context),
    );
  }

  void _showDetails(BuildContext context) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(log['event_type'] as String? ?? 'Log Detail'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: log.entries
              .where((e) => e.key != 'event_payload')
              .map((e) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 140,
                          child: Text(e.key,
                              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
                        ),
                        Expanded(
                            child: Text('${e.value}',
                                style: const TextStyle(fontSize: 12))),
                      ],
                    ),
                  ))
              .toList(),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
      ),
    );
  }
}
