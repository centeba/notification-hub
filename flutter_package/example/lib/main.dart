import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:notification_hub_ui/core/providers/theme_provider.dart';
import 'package:notification_hub_ui/core/theme/app_colors.dart';
import 'package:notification_hub_ui/core/theme/app_theme.dart';

import 'package:notification_hub_ui/features/dashboard/dashboard_screen.dart';
import 'package:notification_hub_ui/features/history/history_screen.dart';
import 'package:notification_hub_ui/features/integrations/integrations_screen.dart';
import 'package:notification_hub_ui/features/preferences/preferences_screen.dart';
import 'package:notification_hub_ui/features/rules/rules_screen.dart';

void main() {
  runApp(
    ProviderScope(
      // Riverpod 3 automatically retries any provider whose build throws, with
      // exponential backoff and no attempt limit. For this app that turned a
      // terminal error — most commonly a 401 when unauthenticated — into an
      // unbounded request storm that hammered the API and left every screen
      // stuck on a spinner. We manage our own refresh (invalidate on user
      // actions), so disable auto-retry entirely and let failures surface.
      retry: (_, __) => null,
      child: const NotificationHubApp(),
    ),
  );
}

final _router = GoRouter(
  initialLocation: '/dashboard',
  routes: [
    ShellRoute(
      builder: (context, state, child) => _AppShell(child: child),
      routes: [
        GoRoute(
          path: '/dashboard',
          builder: (_, __) => const DashboardScreen(),
        ),
        GoRoute(
          path: '/rules',
          builder: (_, __) => const RulesScreen(),
        ),
        GoRoute(
          path: '/history',
          builder: (_, __) => const HistoryScreen(),
        ),
        GoRoute(
          path: '/integrations',
          builder: (_, __) => const IntegrationsScreen(),
        ),
        GoRoute(
          path: '/preferences',
          builder: (_, __) => const PreferencesScreen(),
        ),
      ],
    ),
  ],
);

class NotificationHubApp extends ConsumerWidget {
  const NotificationHubApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeState = ref.watch(themeProvider);
    final colors = themeState.mode == ThemeMode.dark
        ? _darkColors(themeState.brand)
        : _lightColors(themeState.brand);

    return AppThemeColors(
      colors: colors,
      child: MaterialApp.router(
        title: 'Integration Hub',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.build(themeState.brand, Brightness.light),
        darkTheme: AppTheme.build(themeState.brand, Brightness.dark),
        themeMode: themeState.mode,
        localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      supportedLocales: const [Locale('en')],
        routerConfig: _router,
      ),
    );
  }

  static AppColorSet _lightColors(AppBrand brand) => switch (brand) {
        AppBrand.finance => FinanceColors.light,
        AppBrand.construction => ConstructionColors.light,
      };

  static AppColorSet _darkColors(AppBrand brand) => switch (brand) {
        AppBrand.finance => FinanceColors.dark,
        AppBrand.construction => ConstructionColors.dark,
      };
}

class _AppShell extends StatelessWidget {
  final Widget child;

  const _AppShell({required this.child});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth > 768;

        if (isWide) {
          // Side nav for tablet/desktop
          return Scaffold(
            body: Row(
              children: [
                NavigationRail(
                  selectedIndex: _selectedIndex(context),
                  onDestinationSelected: (i) => _navigate(context, i),
                  extended: constraints.maxWidth > 1200,
                  destinations: const [
                    NavigationRailDestination(
                      icon: Icon(Icons.dashboard_outlined),
                      selectedIcon: Icon(Icons.dashboard),
                      label: Text('Dashboard'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.rule_outlined),
                      selectedIcon: Icon(Icons.rule),
                      label: Text('Rules'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.history_outlined),
                      selectedIcon: Icon(Icons.history),
                      label: Text('History'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.extension_outlined),
                      selectedIcon: Icon(Icons.extension),
                      label: Text('Integrations'),
                    ),
                    NavigationRailDestination(
                      icon: Icon(Icons.tune_outlined),
                      selectedIcon: Icon(Icons.tune),
                      label: Text('Preferences'),
                    ),
                  ],
                ),
                const VerticalDivider(width: 1),
                Expanded(child: child),
              ],
            ),
          );
        }

        // Bottom nav for mobile
        return Scaffold(
          body: child,
          bottomNavigationBar: NavigationBar(
            selectedIndex: _selectedIndex(context),
            onDestinationSelected: (i) => _navigate(context, i),
            destinations: const [
              NavigationDestination(
                icon: Icon(Icons.dashboard_outlined),
                selectedIcon: Icon(Icons.dashboard),
                label: 'Dashboard',
              ),
              NavigationDestination(
                icon: Icon(Icons.rule_outlined),
                selectedIcon: Icon(Icons.rule),
                label: 'Rules',
              ),
              NavigationDestination(
                icon: Icon(Icons.history_outlined),
                selectedIcon: Icon(Icons.history),
                label: 'History',
              ),
              NavigationDestination(
                icon: Icon(Icons.extension_outlined),
                selectedIcon: Icon(Icons.extension),
                label: 'Connect',
              ),
              NavigationDestination(
                icon: Icon(Icons.tune_outlined),
                selectedIcon: Icon(Icons.tune),
                label: 'Prefs',
              ),
            ],
          ),
        );
      },
    );
  }

  int _selectedIndex(BuildContext context) {
    final location = GoRouterState.of(context).uri.path;
    return switch (location) {
      '/dashboard' => 0,
      '/rules' => 1,
      '/history' => 2,
      '/integrations' => 3,
      '/preferences' => 4,
      _ => 0,
    };
  }

  void _navigate(BuildContext context, int index) {
    final paths = [
      '/dashboard',
      '/rules',
      '/history',
      '/integrations',
      '/preferences',
    ];
    context.go(paths[index]);
  }
}
