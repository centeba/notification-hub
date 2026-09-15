/// Flutter UI package for Notification Hub — dashboard, delivery history,
/// routing rules, and per-user preferences over the notification-hub API.
///
/// The host application provides an authenticated API base URL / client; these
/// screens share the host's theme through [AppThemeColors]. Labels are plain
/// English (no i18n framework).
library notification_hub_ui;

// Feature screens
export 'features/dashboard/dashboard_screen.dart';
export 'features/history/history_screen.dart';
export 'features/preferences/preferences_screen.dart';
export 'features/rules/rules_screen.dart';

// Core: API client, providers, theming
export 'core/api/api_client.dart';
export 'core/api/notification_service.dart';
export 'core/providers/notification_provider.dart';
export 'core/providers/theme_provider.dart';
export 'core/theme/app_colors.dart';
export 'core/theme/app_theme.dart';
