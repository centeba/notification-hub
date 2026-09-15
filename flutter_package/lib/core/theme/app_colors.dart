import 'package:flutter/material.dart';

// ── Finance theme ─────────────────────────────────────────────────────────────

class FinanceColors {
  static const light = _FinanceLightColors();
  static const dark = _FinanceDarkColors();
}

class _FinanceLightColors implements AppColorSet {
  const _FinanceLightColors();

  @override Color get primary => const Color(0xFF1B365D);
  @override Color get secondary => const Color(0xFF3B82F6);
  @override Color get accent => const Color(0xFFF59E0B);
  @override Color get surface => const Color(0xFFFFFFFF);
  @override Color get background => const Color(0xFFF8FAFC);
  @override Color get textPrimary => const Color(0xFF1F2937);
  @override Color get textSecondary => const Color(0xFF4B5563);
  @override Color get textMuted => const Color(0xFF6B7280);
  @override Color get success => const Color(0xFF059669);
  @override Color get warning => const Color(0xFFD97706);
  @override Color get error => const Color(0xFFDC2626);
  @override Color get info => const Color(0xFF2563EB);
  @override Color get border => const Color(0xFFE5E7EB);
}

class _FinanceDarkColors implements AppColorSet {
  const _FinanceDarkColors();

  @override Color get primary => const Color(0xFF60A5FA);
  @override Color get secondary => const Color(0xFF93C5FD);
  @override Color get accent => const Color(0xFFFBBF24);
  @override Color get surface => const Color(0xFF1E293B);
  @override Color get background => const Color(0xFF0B1120);
  @override Color get textPrimary => const Color(0xFFE2E8F0);
  @override Color get textSecondary => const Color(0xFF94A3B8);
  @override Color get textMuted => const Color(0xFF64748B);
  @override Color get success => const Color(0xFF34D399);
  @override Color get warning => const Color(0xFFFBBF24);
  @override Color get error => const Color(0xFFF87171);
  @override Color get info => const Color(0xFF60A5FA);
  @override Color get border => const Color(0xFF334155);
}

// ── Construction theme ────────────────────────────────────────────────────────

class ConstructionColors {
  static const light = _ConstructionLightColors();
  static const dark = _ConstructionDarkColors();
}

class _ConstructionLightColors implements AppColorSet {
  const _ConstructionLightColors();

  @override Color get primary => const Color(0xFF0F2744);
  @override Color get secondary => const Color(0xFF4A5568);
  @override Color get accent => const Color(0xFFEA580C);
  @override Color get surface => const Color(0xFFFFFFFF);
  @override Color get background => const Color(0xFFFAFAF9);
  @override Color get textPrimary => const Color(0xFF1C1917);
  @override Color get textSecondary => const Color(0xFF44403C);
  @override Color get textMuted => const Color(0xFF78716C);
  @override Color get success => const Color(0xFF16A34A);
  @override Color get warning => const Color(0xFFCA8A04);
  @override Color get error => const Color(0xFFDC2626);
  @override Color get info => const Color(0xFF0284C7);
  @override Color get border => const Color(0xFFE7E5E4);
}

class _ConstructionDarkColors implements AppColorSet {
  const _ConstructionDarkColors();

  @override Color get primary => const Color(0xFF60A5FA);
  @override Color get secondary => const Color(0xFFA8A29E);
  @override Color get accent => const Color(0xFFFB923C);
  @override Color get surface => const Color(0xFF292524);
  @override Color get background => const Color(0xFF1C1917);
  @override Color get textPrimary => const Color(0xFFFAFAF9);
  @override Color get textSecondary => const Color(0xFFA8A29E);
  @override Color get textMuted => const Color(0xFF78716C);
  @override Color get success => const Color(0xFF4ADE80);
  @override Color get warning => const Color(0xFFFBBF24);
  @override Color get error => const Color(0xFFF87171);
  @override Color get info => const Color(0xFF38BDF8);
  @override Color get border => const Color(0xFF44403C);
}

// ── Shared interface ──────────────────────────────────────────────────────────

abstract interface class AppColorSet {
  Color get primary;
  Color get secondary;
  Color get accent;
  Color get surface;
  Color get background;
  Color get textPrimary;
  Color get textSecondary;
  Color get textMuted;
  Color get success;
  Color get warning;
  Color get error;
  Color get info;
  Color get border;
}

// ── Convenience extension ─────────────────────────────────────────────────────

extension StatusColors on BuildContext {
  Color statusColor(String status) {
    final colors = AppThemeColors.of(this);
    return switch (status) {
      'sent' => colors.success,
      'failed' => colors.error,
      'pending' || 'bounced' => colors.warning,
      _ => colors.textMuted,
    };
  }
}

// Accessed via InheritedWidget provided by AppTheme
class AppThemeColors extends InheritedWidget {
  final AppColorSet colors;

  const AppThemeColors({
    super.key,
    required this.colors,
    required super.child,
  });

  static AppColorSet of(BuildContext context) {
    final result = context.dependOnInheritedWidgetOfExactType<AppThemeColors>();
    assert(result != null, 'No AppThemeColors found in context');
    return result!.colors;
  }

  @override
  bool updateShouldNotify(AppThemeColors old) => colors != old.colors;
}
