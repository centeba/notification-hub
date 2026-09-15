import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/providers/notification_provider.dart';
import 'rule_builder_dialog.dart';

class RulesScreen extends ConsumerWidget {
  const RulesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rulesAsync = ref.watch(rulesProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Notification Rules'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            onPressed: () => _showRuleBuilder(context, ref),
          ),
        ],
      ),
      body: rulesAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (data) {
          final rules = (data['data'] as List?) ?? [];
          if (rules.isEmpty) {
            return const Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.rule, size: 64, color: Colors.grey),
                  SizedBox(height: 16),
                  Text('No rules yet. Create your first rule to get started.'),
                ],
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: rules.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (context, i) => _RuleCard(
              rule: rules[i] as Map<String, dynamic>,
              onDelete: () async {
                final service = ref.read(notificationServiceProvider);
                await service.deleteRule(rules[i]['id'] as String);
                ref.invalidate(rulesProvider);
              },
            ),
          );
        },
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _showRuleBuilder(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('New Rule'),
      ),
    );
  }

  void _showRuleBuilder(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (_) => RuleBuilderDialog(
        onCreated: () => ref.invalidate(rulesProvider),
      ),
    );
  }
}

class _RuleCard extends StatelessWidget {
  final Map<String, dynamic> rule;
  final VoidCallback onDelete;

  const _RuleCard({required this.rule, required this.onDelete});

  @override
  Widget build(BuildContext context) {
    final isActive = rule['is_active'] as bool? ?? false;
    final strategy = rule['recipient_strategy'] as String? ?? '';
    final channels = (rule['channel_ids'] as List?)?.length ?? 0;

    return Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: isActive ? Colors.green.withOpacity(0.1) : Colors.grey.withOpacity(0.1),
          child: Icon(
            isActive ? Icons.notifications_active : Icons.notifications_off,
            color: isActive ? Colors.green : Colors.grey,
          ),
        ),
        title: Text(rule['name'] as String? ?? 'Unnamed Rule'),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 4),
            Row(
              children: [
                _Chip(label: strategy, color: Colors.blue),
                const SizedBox(width: 4),
                _Chip(label: '$channels channels', color: Colors.purple),
                const SizedBox(width: 4),
                _Chip(
                  label: 'P${rule['priority']}',
                  color: Colors.orange,
                ),
              ],
            ),
          ],
        ),
        trailing: PopupMenuButton(
          itemBuilder: (_) => [
            const PopupMenuItem(value: 'edit', child: Text('Edit')),
            const PopupMenuItem(value: 'delete', child: Text('Delete')),
          ],
          onSelected: (value) {
            if (value == 'delete') onDelete();
          },
        ),
        isThreeLine: true,
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final Color color;

  const _Chip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Text(label, style: TextStyle(fontSize: 11, color: color)),
    );
  }
}
