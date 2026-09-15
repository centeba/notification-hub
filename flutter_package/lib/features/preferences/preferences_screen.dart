import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/providers/notification_provider.dart';
import '../../core/providers/theme_provider.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_theme.dart';

class PreferencesScreen extends ConsumerWidget {
  const PreferencesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeState = ref.watch(themeProvider);
    final themeNotifier = ref.read(themeProvider.notifier);
    final prefsAsync = ref.watch(myPreferencesProvider);
    final channelsAsync = ref.watch(channelsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('My Preferences')),
      body: prefsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (prefsData) {
          final prefs = (prefsData['data'] as List?) ?? [];
          return channelsAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => Center(child: Text('Error: $e')),
            data: (channelsData) {
              final channels = (channelsData['data'] as List?) ?? [];
              return SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // ── Appearance ────────────────────────────────────
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Appearance', style: Theme.of(context).textTheme.titleMedium),
                            const SizedBox(height: 16),
                            Text('Theme', style: Theme.of(context).textTheme.bodySmall),
                            const SizedBox(height: 8),
                            SegmentedButton<AppBrand>(
                              segments: const [
                                ButtonSegment(value: AppBrand.finance, label: Text('Finance'), icon: Icon(Icons.account_balance)),
                                ButtonSegment(value: AppBrand.construction, label: Text('Construction'), icon: Icon(Icons.construction)),
                              ],
                              selected: {themeState.brand},
                              onSelectionChanged: (s) => themeNotifier.setBrand(s.first),
                            ),
                            const SizedBox(height: 16),
                            Text('Mode', style: Theme.of(context).textTheme.bodySmall),
                            const SizedBox(height: 8),
                            SegmentedButton<ThemeMode>(
                              segments: const [
                                ButtonSegment(value: ThemeMode.light, label: Text('Light'), icon: Icon(Icons.light_mode)),
                                ButtonSegment(value: ThemeMode.system, label: Text('System'), icon: Icon(Icons.brightness_auto)),
                                ButtonSegment(value: ThemeMode.dark, label: Text('Dark'), icon: Icon(Icons.dark_mode)),
                              ],
                              selected: {themeState.mode},
                              onSelectionChanged: (s) => themeNotifier.setMode(s.first),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    // ── Language preference ───────────────────────────
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Language', style: Theme.of(context).textTheme.titleMedium),
                            const SizedBox(height: 8),
                            DropdownButtonFormField<String>(
                              decoration: const InputDecoration(
                                labelText: 'Preferred Language',
                                border: OutlineInputBorder(),
                              ),
                              value: 'en',
                              items: const [
                                DropdownMenuItem(value: 'en', child: Text('English')),
                                DropdownMenuItem(value: 'es', child: Text('Spanish')),
                                DropdownMenuItem(value: 'fr', child: Text('French')),
                              ],
                              onChanged: (_) {},
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    // ── Channel preferences ───────────────────────────
                    Text('Notification Channels', style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    ...channels.map((ch) {
                      final channelId = ch['id'] as String;
                      final channelName = ch['name'] as String;
                      final pref = prefs.firstWhere(
                        (p) => (p as Map<String, dynamic>)['channel_id'] == channelId,
                        orElse: () => <String, dynamic>{'is_enabled': true},
                      ) as Map<String, dynamic>;
                      final isEnabled = pref['is_enabled'] as bool? ?? true;

                      return Card(
                        child: SwitchListTile(
                          title: Text(channelName.toUpperCase()),
                          subtitle: Text(_channelDescription(channelName)),
                          value: isEnabled,
                          onChanged: (val) async {
                            final service = ref.read(notificationServiceProvider);
                            await service.upsertMyPreference(channelId, {
                              'channel_id': channelId,
                              'is_enabled': val,
                            });
                            ref.invalidate(myPreferencesProvider);
                          },
                        ),
                      );
                    }),
                    const SizedBox(height: 16),
                    // ── Quiet hours ───────────────────────────────────
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Quiet Hours', style: Theme.of(context).textTheme.titleMedium),
                            const SizedBox(height: 8),
                            Text(
                              'Notifications will not be sent during quiet hours.',
                              style: TextStyle(color: AppThemeColors.of(context).textMuted, fontSize: 12),
                            ),
                            const SizedBox(height: 16),
                            Row(
                              children: [
                                Expanded(
                                  child: TextFormField(
                                    decoration: const InputDecoration(
                                      labelText: 'Start Time',
                                      hintText: '22:00',
                                      border: OutlineInputBorder(),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 16),
                                Expanded(
                                  child: TextFormField(
                                    decoration: const InputDecoration(
                                      labelText: 'End Time',
                                      hintText: '08:00',
                                      border: OutlineInputBorder(),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
          );
        },
      ),
    );
  }

  String _channelDescription(String channel) => switch (channel) {
        'email' => 'Receive notifications via email',
        'sms' => 'Receive notifications via SMS to your mobile phone',
        'webhook' => 'Forward notifications to configured API endpoints',
        _ => '',
      };
}
