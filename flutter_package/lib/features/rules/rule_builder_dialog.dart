import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/providers/notification_provider.dart';

/// Step-by-step rule builder wizard
class RuleBuilderDialog extends ConsumerStatefulWidget {
  final VoidCallback onCreated;

  const RuleBuilderDialog({super.key, required this.onCreated});

  @override
  ConsumerState<RuleBuilderDialog> createState() => _RuleBuilderDialogState();
}

class _RuleBuilderDialogState extends ConsumerState<RuleBuilderDialog> {
  int _step = 0;
  final _formKey = GlobalKey<FormState>();

  String _name = '';
  String _eventTypeId = '';
  List<String> _channelIds = [];
  String _recipientStrategy = 'all_users';
  String _templateId = '';
  int _priority = 5;
  final List<Map<String, dynamic>> _conditions = [];

  final _steps = ['Name & Event', 'Channels', 'Recipients', 'Template', 'Review'];

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 600, maxHeight: 700),
        child: Column(
          children: [
            // ── Step indicator ────────────────────────────────────────
            Container(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: List.generate(_steps.length, (i) {
                  final isActive = i == _step;
                  final isDone = i < _step;
                  return Expanded(
                    child: Row(
                      children: [
                        CircleAvatar(
                          radius: 14,
                          backgroundColor: isDone
                              ? Colors.green
                              : isActive
                                  ? Theme.of(context).primaryColor
                                  : Colors.grey.shade300,
                          child: isDone
                              ? const Icon(Icons.check, size: 14, color: Colors.white)
                              : Text(
                                  '${i + 1}',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: isActive ? Colors.white : Colors.grey,
                                  ),
                                ),
                        ),
                        if (i < _steps.length - 1)
                          Expanded(
                            child: Divider(
                              color: isDone ? Colors.green : Colors.grey.shade300,
                            ),
                          ),
                      ],
                    ),
                  );
                }),
              ),
            ),
            Text(
              _steps[_step],
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const Divider(),
            // ── Step content ──────────────────────────────────────────
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Form(key: _formKey, child: _buildStep()),
              ),
            ),
            // ── Navigation ────────────────────────────────────────────
            const Divider(),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  if (_step > 0)
                    OutlinedButton(
                      onPressed: () => setState(() => _step--),
                      child: const Text('Back'),
                    )
                  else
                    TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('Cancel'),
                    ),
                  ElevatedButton(
                    onPressed: _step == _steps.length - 1 ? _submit : _nextStep,
                    child: Text(_step == _steps.length - 1 ? 'Create Rule' : 'Next'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStep() {
    switch (_step) {
      case 0:
        return _buildNameEventStep();
      case 1:
        return _buildChannelsStep();
      case 2:
        return _buildRecipientsStep();
      case 3:
        return _buildTemplateStep();
      case 4:
        return _buildReviewStep();
      default:
        return const SizedBox.shrink();
    }
  }

  Widget _buildNameEventStep() {
    final eventTypesAsync = ref.watch(
      FutureProvider((ref) => ref.read(notificationServiceProvider).getRules()).future as dynamic,
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextFormField(
          decoration: const InputDecoration(
            labelText: 'Rule Name *',
            hintText: 'e.g. Notify admin on new order',
          ),
          validator: (v) => (v?.isEmpty ?? true) ? 'Name is required' : null,
          onChanged: (v) => _name = v,
        ),
        const SizedBox(height: 16),
        TextFormField(
          decoration: const InputDecoration(
            labelText: 'Event Type ID *',
            hintText: 'Select from available event types',
          ),
          validator: (v) => (v?.isEmpty ?? true) ? 'Event type is required' : null,
          onChanged: (v) => _eventTypeId = v,
        ),
        const SizedBox(height: 16),
        TextFormField(
          decoration: const InputDecoration(labelText: 'Priority (1-10)'),
          keyboardType: TextInputType.number,
          initialValue: '5',
          onChanged: (v) => _priority = int.tryParse(v) ?? 5,
        ),
        const SizedBox(height: 16),
        const Text('Conditions (optional)', style: TextStyle(fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        const Text('Add conditions to filter when this rule fires:',
            style: TextStyle(color: Colors.grey, fontSize: 12)),
        ..._conditions.asMap().entries.map((e) => _ConditionRow(
              condition: e.value,
              onRemove: () => setState(() => _conditions.removeAt(e.key)),
            )),
        TextButton.icon(
          icon: const Icon(Icons.add),
          label: const Text('Add Condition'),
          onPressed: () => setState(() => _conditions.add({
                'field': '',
                'operator': 'eq',
                'value': '',
              })),
        ),
      ],
    );
  }

  Widget _buildChannelsStep() {
    final channelsAsync = ref.watch(channelsProvider);
    return channelsAsync.when(
      loading: () => const CircularProgressIndicator(),
      error: (e, _) => Text('Error loading channels: $e'),
      data: (data) {
        final channels = (data['data'] as List?) ?? [];
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Select notification channels:'),
            const SizedBox(height: 8),
            ...channels.map((ch) {
              final id = ch['id'] as String;
              final name = ch['name'] as String;
              return CheckboxListTile(
                title: Text(name.toUpperCase()),
                value: _channelIds.contains(id),
                onChanged: (val) {
                  setState(() {
                    if (val == true) {
                      _channelIds.add(id);
                    } else {
                      _channelIds.remove(id);
                    }
                  });
                },
              );
            }),
          ],
        );
      },
    );
  }

  Widget _buildRecipientsStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Recipient Strategy'),
        const SizedBox(height: 8),
        ...['all_users', 'role', 'specific', 'event_field'].map(
          (s) => RadioListTile<String>(
            title: Text(_strategyLabel(s)),
            subtitle: Text(_strategyDescription(s)),
            value: s,
            groupValue: _recipientStrategy,
            onChanged: (v) => setState(() => _recipientStrategy = v!),
          ),
        ),
      ],
    );
  }

  Widget _buildTemplateStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextFormField(
          decoration: const InputDecoration(
            labelText: 'Template ID *',
            hintText: 'Select from available templates',
          ),
          validator: (v) => (v?.isEmpty ?? true) ? 'Template is required' : null,
          onChanged: (v) => _templateId = v,
        ),
      ],
    );
  }

  Widget _buildReviewStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _ReviewRow(label: 'Name', value: _name),
        _ReviewRow(label: 'Event Type', value: _eventTypeId),
        _ReviewRow(label: 'Channels', value: _channelIds.join(', ')),
        _ReviewRow(label: 'Recipients', value: _strategyLabel(_recipientStrategy)),
        _ReviewRow(label: 'Template', value: _templateId),
        _ReviewRow(label: 'Priority', value: '$_priority'),
        _ReviewRow(label: 'Conditions', value: '${_conditions.length} condition(s)'),
      ],
    );
  }

  void _nextStep() {
    if (_formKey.currentState?.validate() ?? false) {
      setState(() => _step++);
    }
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      final service = ref.read(notificationServiceProvider);
      await service.createRule({
        'name': _name,
        'event_type_id': _eventTypeId,
        'channel_ids': _channelIds,
        'recipient_strategy': _recipientStrategy,
        'template_id': _templateId,
        'priority': _priority,
        'conditions': _conditions,
      });
      widget.onCreated();
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to create rule: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  String _strategyLabel(String s) => switch (s) {
        'all_users' => 'All Company Users',
        'role' => 'By Role',
        'specific' => 'Specific Users',
        'event_field' => 'From Event Payload',
        _ => s,
      };

  String _strategyDescription(String s) => switch (s) {
        'all_users' => 'Send to every user in the company',
        'role' => 'Send to users with a specific role (e.g. company_admin)',
        'specific' => 'Send to a fixed list of user IDs',
        'event_field' => 'Extract user_id from the event payload field',
        _ => '',
      };
}

class _ConditionRow extends StatelessWidget {
  final Map<String, dynamic> condition;
  final VoidCallback onRemove;

  const _ConditionRow({required this.condition, required this.onRemove});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: TextFormField(
            decoration: const InputDecoration(labelText: 'Field', isDense: true),
            onChanged: (v) => condition['field'] = v,
          ),
        ),
        const SizedBox(width: 8),
        SizedBox(
          width: 100,
          child: DropdownButtonFormField<String>(
            value: condition['operator'] as String? ?? 'eq',
            items: ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'in']
                .map((op) => DropdownMenuItem(value: op, child: Text(op)))
                .toList(),
            onChanged: (v) => condition['operator'] = v,
            decoration: const InputDecoration(labelText: 'Op', isDense: true),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: TextFormField(
            decoration: const InputDecoration(labelText: 'Value', isDense: true),
            onChanged: (v) => condition['value'] = v,
          ),
        ),
        IconButton(icon: const Icon(Icons.remove_circle, color: Colors.red), onPressed: onRemove),
      ],
    );
  }
}

class _ReviewRow extends StatelessWidget {
  final String label;
  final String value;

  const _ReviewRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(label, style: const TextStyle(fontWeight: FontWeight.bold)),
          ),
          Expanded(child: Text(value.isEmpty ? '—' : value)),
        ],
      ),
    );
  }
}
