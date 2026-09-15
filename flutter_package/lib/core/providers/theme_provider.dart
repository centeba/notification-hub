import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../theme/app_theme.dart';

class ThemeState {
  final AppBrand brand;
  final ThemeMode mode;

  const ThemeState({this.brand = AppBrand.finance, this.mode = ThemeMode.system});

  ThemeState copyWith({AppBrand? brand, ThemeMode? mode}) =>
      ThemeState(brand: brand ?? this.brand, mode: mode ?? this.mode);
}

class ThemeNotifier extends StateNotifier<ThemeState> {
  ThemeNotifier() : super(const ThemeState());

  void setBrand(AppBrand brand) => state = state.copyWith(brand: brand);
  void setMode(ThemeMode mode) => state = state.copyWith(mode: mode);
}

final themeProvider = StateNotifierProvider<ThemeNotifier, ThemeState>(
  (_) => ThemeNotifier(),
);
