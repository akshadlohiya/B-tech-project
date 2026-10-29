import 'package:flutter/painting.dart';
import 'package:flutter_application/scene3d.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('camera projects the origin to the screen centre', () {
    final cam = Cam()..update(const Size(400, 800));
    final o = cam.project(0, 0, 0)!;
    expect(o.dx, closeTo(200, 0.01));
    expect(o.dy, closeTo(400, 0.01));
  });
}
