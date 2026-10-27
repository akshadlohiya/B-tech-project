import 'package:flutter/material.dart';
import 'api.dart';
import 'map_manager.dart';
import 'util.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  runApp(const UwbApp());
}

class UwbApp extends StatelessWidget {
  const UwbApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'UWB Twin',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        useMaterial3: true,
        scaffoldBackgroundColor: bgDark,
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2563EB), brightness: Brightness.dark).copyWith(surface: bgDark),
        appBarTheme: const AppBarTheme(backgroundColor: bgDark, elevation: 0),
        dialogTheme: const DialogThemeData(backgroundColor: cardBg),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFF0F172A),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: cardBorder)),
          enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: const BorderSide(color: cardBorder)),
          isDense: true,
        ),
      ),
      home: const MapManager(),
    );
  }
}
