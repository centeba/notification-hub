import 'package:flutter/widgets.dart';

/// Self-contained internationalization shim for `notification_hub_ui`.
///
/// The package was originally coupled to a private `multi_lang_sdk` git
/// dependency. This shim reproduces the small surface the screens use
/// (`MultiLangLocalizations.of(context)?.translate(key)` plus a localizations
/// delegate) with **no external dependency**.
///
/// By default `translate` returns `null`, so every call site falls back to its
/// hardcoded default string (all screens already pass `?? 'Default'`). A host
/// app that runs a translation backend can supply its own translator:
///
/// ```dart
/// MaterialApp.router(
///   localizationsDelegates: [
///     MultiLangDelegate(
///       namespace: 'dashboard',
///       translator: (ns, locale, key) => myCatalog[locale.languageCode]?[key],
///     ),
///     // ...global delegates
///   ],
/// );
/// ```
typedef MultiLangTranslator = String? Function(
  String namespace,
  Locale locale,
  String key,
);

/// Placeholder for the former remote translation client. Retained so existing
/// call sites compile; the shim performs no network I/O — wire a
/// [MultiLangTranslator] instead to source strings (e.g. from an API you fetch).
class MultiLangApiClient {
  const MultiLangApiClient({required this.baseUrl});

  final String baseUrl;
}

/// Localizations object resolved from the widget tree via [of].
class MultiLangLocalizations {
  const MultiLangLocalizations({
    required this.locale,
    this.namespace = '',
    this.translator,
  });

  final Locale locale;
  final String namespace;
  final MultiLangTranslator? translator;

  static MultiLangLocalizations? of(BuildContext context) =>
      Localizations.of<MultiLangLocalizations>(context, MultiLangLocalizations);

  /// Returns the translated string for [key], or `null` when no translator is
  /// registered (callers supply their own fallback).
  String? translate(String key) => translator?.call(namespace, locale, key);
}

/// A [LocalizationsDelegate] that installs [MultiLangLocalizations].
class MultiLangDelegate extends LocalizationsDelegate<MultiLangLocalizations> {
  const MultiLangDelegate({
    this.apiClient,
    this.namespace = '',
    this.translator,
    this.supportedLanguageCodes = const {'en', 'es', 'fr'},
  });

  final MultiLangApiClient? apiClient;
  final String namespace;
  final MultiLangTranslator? translator;
  final Set<String> supportedLanguageCodes;

  @override
  bool isSupported(Locale locale) =>
      supportedLanguageCodes.contains(locale.languageCode);

  @override
  Future<MultiLangLocalizations> load(Locale locale) async =>
      MultiLangLocalizations(
        locale: locale,
        namespace: namespace,
        translator: translator,
      );

  @override
  bool shouldReload(MultiLangDelegate old) =>
      old.translator != translator || old.namespace != namespace;
}
