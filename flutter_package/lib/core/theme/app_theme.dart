import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'app_colors.dart';

enum AppBrand { finance, construction }

class AppTheme {
  AppTheme._();

  static ThemeData build(AppBrand brand, Brightness brightness) {
    final colors = _colorsFor(brand, brightness);
    final isDark = brightness == Brightness.dark;

    final colorScheme = ColorScheme(
      brightness: brightness,
      primary: colors.primary,
      onPrimary: Colors.white,
      primaryContainer: colors.primary.withValues(alpha: 0.12),
      onPrimaryContainer: colors.primary,
      secondary: colors.secondary,
      onSecondary: Colors.white,
      secondaryContainer: colors.secondary.withValues(alpha: 0.12),
      onSecondaryContainer: colors.secondary,
      tertiary: colors.accent,
      onTertiary: Colors.white,
      tertiaryContainer: colors.accent.withValues(alpha: 0.12),
      onTertiaryContainer: colors.accent,
      error: colors.error,
      onError: Colors.white,
      errorContainer: colors.error.withValues(alpha: 0.12),
      onErrorContainer: colors.error,
      surface: colors.surface,
      onSurface: colors.textPrimary,
      surfaceContainerHighest: colors.background,
      onSurfaceVariant: colors.textSecondary,
      outline: colors.border,
      outlineVariant: colors.border.withValues(alpha: 0.5),
      shadow: Colors.black,
      scrim: Colors.black54,
      inverseSurface: isDark ? colors.surface : colors.background,
      onInverseSurface: isDark ? colors.textPrimary : Colors.white,
      inversePrimary: isDark ? colors.primary : const Color(0xFF93C5FD),
    );

    final textTheme = _buildTextTheme(colors);

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: colors.background,
      textTheme: textTheme,
      appBarTheme: AppBarTheme(
        backgroundColor: colors.primary,
        foregroundColor: Colors.white,
        elevation: 0,
        titleTextStyle: GoogleFonts.plusJakartaSans(
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: Colors.white,
        ),
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: colors.surface,
        selectedIconTheme: IconThemeData(color: colors.primary),
        selectedLabelTextStyle: TextStyle(color: colors.primary, fontWeight: FontWeight.w600),
        unselectedIconTheme: IconThemeData(color: colors.textMuted),
        unselectedLabelTextStyle: TextStyle(color: colors.textMuted),
        indicatorColor: colors.primary.withValues(alpha: 0.12),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: colors.surface,
        indicatorColor: colors.primary.withValues(alpha: 0.12),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return IconThemeData(color: colors.primary);
          }
          return IconThemeData(color: colors.textMuted);
        }),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return TextStyle(color: colors.primary, fontWeight: FontWeight.w600, fontSize: 12);
          }
          return TextStyle(color: colors.textMuted, fontSize: 12);
        }),
      ),
      cardTheme: CardThemeData(
        color: colors.surface,
        elevation: 2,
        shadowColor: Colors.black.withValues(alpha: isDark ? 0.4 : 0.08),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: colors.border, width: 0.5),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: colors.primary,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w600),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: colors.primary,
          side: BorderSide(color: colors.primary),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w600),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: colors.primary,
          textStyle: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w600),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: colors.surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: colors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: colors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: BorderSide(color: colors.primary, width: 2),
        ),
        labelStyle: TextStyle(color: colors.textSecondary),
        hintStyle: TextStyle(color: colors.textMuted),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: colors.background,
        selectedColor: colors.primary.withValues(alpha: 0.12),
        labelStyle: TextStyle(color: colors.textPrimary, fontSize: 13),
        side: BorderSide(color: colors.border),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      dividerTheme: DividerThemeData(color: colors.border, thickness: 1),
      switchTheme: SwitchThemeData(
        thumbColor: WidgetStateProperty.resolveWith((states) =>
            states.contains(WidgetState.selected) ? colors.primary : colors.textMuted),
        trackColor: WidgetStateProperty.resolveWith((states) =>
            states.contains(WidgetState.selected)
                ? colors.primary.withValues(alpha: 0.4)
                : colors.border),
      ),
    );
  }

  static AppColorSet _colorsFor(AppBrand brand, Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    return switch (brand) {
      AppBrand.finance => isDark ? FinanceColors.dark : FinanceColors.light,
      AppBrand.construction => isDark ? ConstructionColors.dark : ConstructionColors.light,
    };
  }

  static TextTheme _buildTextTheme(AppColorSet colors) {
    return TextTheme(
      displayLarge: GoogleFonts.plusJakartaSans(fontSize: 48, fontWeight: FontWeight.w700, color: colors.textPrimary, letterSpacing: -0.025 * 48),
      displayMedium: GoogleFonts.plusJakartaSans(fontSize: 36, fontWeight: FontWeight.w700, color: colors.textPrimary),
      displaySmall: GoogleFonts.plusJakartaSans(fontSize: 28, fontWeight: FontWeight.w600, color: colors.textPrimary),
      headlineLarge: GoogleFonts.plusJakartaSans(fontSize: 24, fontWeight: FontWeight.w700, color: colors.textPrimary),
      headlineMedium: GoogleFonts.plusJakartaSans(fontSize: 20, fontWeight: FontWeight.w600, color: colors.textPrimary),
      headlineSmall: GoogleFonts.plusJakartaSans(fontSize: 18, fontWeight: FontWeight.w600, color: colors.textPrimary),
      titleLarge: GoogleFonts.plusJakartaSans(fontSize: 16, fontWeight: FontWeight.w600, color: colors.textPrimary),
      titleMedium: GoogleFonts.plusJakartaSans(fontSize: 15, fontWeight: FontWeight.w600, color: colors.textPrimary),
      titleSmall: GoogleFonts.plusJakartaSans(fontSize: 13, fontWeight: FontWeight.w600, color: colors.textSecondary),
      bodyLarge: GoogleFonts.inter(fontSize: 16, fontWeight: FontWeight.w400, color: colors.textPrimary),
      bodyMedium: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w400, color: colors.textPrimary),
      bodySmall: GoogleFonts.inter(fontSize: 12, fontWeight: FontWeight.w400, color: colors.textSecondary),
      labelLarge: GoogleFonts.inter(fontSize: 14, fontWeight: FontWeight.w500, color: colors.textPrimary),
      labelMedium: GoogleFonts.inter(fontSize: 12, fontWeight: FontWeight.w500, color: colors.textSecondary),
      labelSmall: GoogleFonts.inter(fontSize: 11, fontWeight: FontWeight.w500, color: colors.textMuted),
    );
  }
}
