import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/providers/notification_provider.dart';
import '../../core/theme/app_colors.dart';
import '../../core/i18n.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final logsAsync = ref.watch(deliveryLogsProvider({'limit': 100}));

    return Scaffold(
      appBar: AppBar(title: Text(MultiLangLocalizations.of(context)?.translate('dashboard.title') ?? 'Dashboard')),
      body: logsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (data) {
          final logs = (data['data'] as List?) ?? [];
          final sent = logs.where((l) => l['status'] == 'sent').length;
          final failed = logs.where((l) => l['status'] == 'failed').length;
          final total = logs.length;
          final rate = total > 0 ? (sent / total * 100).toStringAsFixed(1) : '0';

          return LayoutBuilder(
            builder: (context, constraints) {
              final isWide = constraints.maxWidth > 768;
              return SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // ── Stats row ───────────────────────────────────────
                    isWide
                        ? Row(
                            children: [
                              _StatCard(title: MultiLangLocalizations.of(context)?.translate('dashboard.stats.total_sent') ?? 'Total Sent', value: '$sent', color: AppThemeColors.of(context).success),
                              const SizedBox(width: 16),
                              _StatCard(title: MultiLangLocalizations.of(context)?.translate('dashboard.stats.total_failed') ?? 'Total Failed', value: '$failed', color: AppThemeColors.of(context).error),
                              const SizedBox(width: 16),
                              _StatCard(title: MultiLangLocalizations.of(context)?.translate('dashboard.stats.delivery_rate') ?? 'Delivery Rate', value: '$rate%', color: AppThemeColors.of(context).info),
                            ].map((w) => Expanded(child: w)).toList(),
                          )
                        : Column(
                            children: [
                              _StatCard(title: MultiLangLocalizations.of(context)?.translate('dashboard.stats.total_sent') ?? 'Total Sent', value: '$sent', color: AppThemeColors.of(context).success),
                              const SizedBox(height: 8),
                              _StatCard(title: MultiLangLocalizations.of(context)?.translate('dashboard.stats.total_failed') ?? 'Total Failed', value: '$failed', color: AppThemeColors.of(context).error),
                              const SizedBox(height: 8),
                              _StatCard(title: MultiLangLocalizations.of(context)?.translate('dashboard.stats.delivery_rate') ?? 'Delivery Rate', value: '$rate%', color: AppThemeColors.of(context).info),
                            ],
                          ),
                    const SizedBox(height: 24),
                    // ── Channel breakdown pie chart ─────────────────────
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(MultiLangLocalizations.of(context)?.translate('dashboard.charts.by_channel') ?? 'By Channel', style: Theme.of(context).textTheme.titleMedium),
                            const SizedBox(height: 16),
                            SizedBox(
                              height: 200,
                              child: _ChannelPieChart(logs: logs),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    // ── Recent activity ─────────────────────────────────
                    Text(MultiLangLocalizations.of(context)?.translate('dashboard.recent_activity') ?? 'Recent Activity', style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    ...logs.take(10).map((log) => _LogTile(log: log as Map<String, dynamic>)),
                  ],
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final Color color;

  const _StatCard({required this.title, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 8),
            Text(value, style: Theme.of(context).textTheme.headlineMedium?.copyWith(color: color)),
          ],
        ),
      ),
    );
  }
}

class _ChannelPieChart extends StatelessWidget {
  final List logs;

  const _ChannelPieChart({required this.logs});

  @override
  Widget build(BuildContext context) {
    final counts = <String, int>{};
    for (final log in logs) {
      final channel = log['channel'] as String? ?? 'unknown';
      counts[channel] = (counts[channel] ?? 0) + 1;
    }

    final appColors = AppThemeColors.of(context);
    final colors = {'email': appColors.info, 'sms': appColors.success, 'webhook': appColors.accent};
    final sections = counts.entries.map((e) {
      final color = colors[e.key] ?? Colors.grey;
      return PieChartSectionData(
        value: e.value.toDouble(),
        title: '${e.key}\n${e.value}',
        color: color,
        radius: 80,
        titleStyle: const TextStyle(fontSize: 12, color: Colors.white),
      );
    }).toList();

    if (sections.isEmpty) {
      return const Center(child: Text('No data'));
    }

    return PieChart(PieChartData(sections: sections, sectionsSpace: 2));
  }
}

class _LogTile extends StatelessWidget {
  final Map<String, dynamic> log;

  const _LogTile({required this.log});

  @override
  Widget build(BuildContext context) {
    final status = log['status'] as String? ?? '';
    final statusColor = context.statusColor(status);

    return ListTile(
      leading: CircleAvatar(
        backgroundColor: statusColor.withValues(alpha: 0.15),
        child: Icon(
          status == 'sent' ? Icons.check_circle : Icons.error,
          color: statusColor,
          size: 20,
        ),
      ),
      title: Text(log['event_type'] as String? ?? 'Unknown'),
      subtitle: Text(log['channel'] as String? ?? ''),
      trailing: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: statusColor.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Text(status, style: TextStyle(color: statusColor, fontSize: 12)),
      ),
    );
  }
}
