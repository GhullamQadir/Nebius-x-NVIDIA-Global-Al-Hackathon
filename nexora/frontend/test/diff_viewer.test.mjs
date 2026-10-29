import test from 'node:test';
import assert from 'node:assert/strict';

import {
  parseDiff,
  renderSplitView,
  renderUnifiedView,
  renderCodeView,
  renderDiffViewer,
} from '../js/ui/diff_viewer.js';

const SAMPLE_PATCH = `diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,5 +1,6 @@
 def multiply(a, b):
-    return a + b
+    """Return product of a and b"""
+    return a * b
`;

test('parseDiff accurately extracts files, hunks, additions and deletions', () => {
  const files = parseDiff(SAMPLE_PATCH);
  assert.equal(files.length, 1);
  assert.equal(files[0].to, 'calculator.py');
  assert.equal(files[0].additions, 2);
  assert.equal(files[0].deletions, 1);
  assert.equal(files[0].hunks.length, 1);
});

test('renderSplitView produces side-by-side tables with aligned deletion and addition cells', () => {
  const files = parseDiff(SAMPLE_PATCH);
  const html = renderSplitView(files);
  assert.ok(html.includes('diff-split-table'));
  assert.ok(html.includes('Original (Before)'));
  assert.ok(html.includes('Proposed (After)'));
  assert.ok(html.includes('return a + b'));
  assert.ok(html.includes('return a * b'));
  assert.ok(html.includes('diff-code-cell del'));
  assert.ok(html.includes('diff-code-cell add'));
});

test('renderUnifiedView produces unified diff with dual line numbers', () => {
  const files = parseDiff(SAMPLE_PATCH);
  const html = renderUnifiedView(files);
  assert.ok(html.includes('diff-unified-table'));
  assert.ok(html.includes('diff-del-row'));
  assert.ok(html.includes('diff-add-row'));
  assert.ok(html.includes('@@ -1,5 +1,6 @@'));
});

test('renderCodeView numbers all lines cleanly using data-line attributes to prevent clipboard contamination', () => {
  const code = 'def foo():\n    return 42';
  const html = renderCodeView(code, 'foo.py');
  assert.ok(html.includes('diff-code-table'));
  assert.ok(html.includes('foo.py'));
  assert.ok(html.includes('def foo():'));
  assert.ok(html.includes('return 42'));
  assert.ok(html.includes('data-line="1"'));
  assert.ok(html.includes('data-line="2"'));
  assert.ok(html.includes('diff-copy-code-btn icon-only'));
  assert.ok(!html.includes('<span>Copy Code</span>'));
});

test('renderCodeView enables live interactive preview for HTML files', () => {
  const htmlDoc = '<!DOCTYPE html><html><body><h1>Portfolio</h1></body></html>';
  const html = renderCodeView(htmlDoc, 'index.html');
  assert.ok(html.includes('diff-preview-btn'));
  assert.ok(html.includes('diff-preview-iframe'));
  assert.ok(html.includes('Live Preview'));
});

test('renderDiffViewer outputs full component with mode switcher buttons', () => {
  const html = renderDiffViewer(SAMPLE_PATCH, 'def multiply(a, b):\n    return a * b', 'split');
  assert.ok(html.includes('visual-diff-component'));
  assert.ok(html.includes('data-mode="split"'));
  assert.ok(html.includes('data-mode="unified"'));
  assert.ok(html.includes('data-mode="code"'));
  assert.ok(html.includes('+2'));
  assert.ok(html.includes('-1'));
});

test('diff_viewer safely escapes XSS injection payloads', () => {
  const xssPatch = `diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -1,1 +1,1 @@
-<script>alert(1)</script>
+<img src=x onerror=alert(2)>
`;
  const html = renderDiffViewer(xssPatch, '<script>alert(3)</script>');
  assert.ok(!/<script\b/i.test(html), 'script tag was not escaped');
  assert.ok(!/<img\b/i.test(html), 'img tag was not escaped');
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('&lt;img'));
});
