/**
 * Phase 5.D — XSS regression tests for the chat/panel Markdown renderer.
 *
 * Untrusted content (model output, task text, repository content) is rendered
 * through `renderMarkdown` and assigned to `innerHTML`, so the renderer must
 * never emit attacker-controlled tags. Run with:
 *
 *   node --test nexora/frontend/test/
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import { renderMarkdown, renderDiff } from '../js/ui/markdown.js';

const PAYLOADS = [
  '<img src=x onerror=alert(1)>',
  '<script>alert(1)</script>',
  '<svg/onload=alert(1)>',
  '<a href="javascript:alert(1)">x</a>',
  '<iframe srcdoc="<script>alert(1)<\/script>"></iframe>',
];

test('paragraph text cannot inject elements (no tag survives)', () => {
  for (const payload of PAYLOADS) {
    const html = renderMarkdown(`hello ${payload} world`);
    assert.ok(!/<(img|script|svg|iframe|a|iframe)\b/i.test(html), `tag leaked for: ${payload}`);
    // A javascript: URL may only survive as inert text, never in an attribute.
    assert.ok(!/(href|src)\s*=\s*["']?\s*javascript:/i.test(html), `attribute-position javascript: URL for: ${payload}`);
  }
});

test('raw "<" in text is escaped', () => {
  assert.ok(renderMarkdown('a < b').includes('a &lt; b'));
});

test('heading path escapes untrusted text', () => {
  const html = renderMarkdown('# <img src=x onerror=alert(1)>');
  assert.ok(!/<img/i.test(html));
  assert.ok(html.includes('&lt;img'));
});

test('blockquote path escapes untrusted text', () => {
  const html = renderMarkdown('> <img src=x onerror=alert(1)>');
  assert.ok(!/<img/i.test(html));
  assert.ok(html.includes('&lt;img'));
});

test('table cell path escapes untrusted text', () => {
  const html = renderMarkdown('| a | b |\n| --- | --- |\n| <img src=x onerror=alert(1)> | ok |');
  assert.ok(!/<img/i.test(html));
  assert.ok(html.includes('&lt;img'));
});

test('list item path escapes untrusted text', () => {
  const html = renderMarkdown('- <img src=x onerror=alert(1)>');
  assert.ok(!/<img/i.test(html));
  assert.ok(html.includes('&lt;img'));
});

test('fenced code content stays escaped', () => {
  const html = renderMarkdown('```js\n<img src=x onerror=alert(1)>\n```');
  assert.ok(!/<img/i.test(html));
  assert.ok(html.includes('&lt;img'));
});

test('renderDiff escapes patch content', () => {
  const html = renderDiff('+<img src=x onerror=alert(1)>');
  assert.ok(!/<img/i.test(html));
});

test('markdown formatting still renders', () => {
  const html = renderMarkdown('**bold** and `code<x>` and [l](https://e.com/?a=1&b=2)');
  assert.ok(html.includes('<strong>bold</strong>'), 'bold lost');
  assert.ok(html.includes('<code>code&lt;x&gt;</code>'), 'inline code lost/unescaped');
  assert.ok(html.includes('href="https://e.com/?a=1&amp;b=2"'), 'link lost or double-escaped');
  assert.ok(!html.includes('&amp;amp;'), 'double escaping introduced');
});

test('tool call cards render with structured HTML and escaped arguments', () => {
  const toolInput = '> ⚡ **Executing Tool:** `repo_read` `{"path": "solution.py"}`\n\n> ✓ **Finished Tool:** `repo_read`\n```\ndef calculate(): pass\n```';
  const html = renderMarkdown(toolInput);
  assert.ok(html.includes('tool-call-card executing'), 'executing card missing');
  assert.ok(html.includes('tool-call-card success'), 'success card missing');
  assert.ok(html.includes('repo_read'), 'tool name missing');
  assert.ok(html.includes('def calculate(): pass'), 'preview code missing');
  assert.ok(!/<(script|img)/i.test(html), 'unsafe tag injected');
});

test('chain of thought accordion renders safely with inner markdown', () => {
  const thoughtInput = '<thought>\nAnalyzing the bug in solution.py:\n- Look at line 10\n- **Fix** the operator\n</thought>';
  const html = renderMarkdown(thoughtInput);
  assert.ok(html.includes('thought-accordion'), 'accordion missing');
  assert.ok(html.includes('thought-summary'), 'summary missing');
  assert.ok(html.includes('<strong>Fix</strong>'), 'inner markdown not rendered');
  assert.ok(!/<script/i.test(html));
});

test('orphan thought tags and reasoning leaks are cleanly stripped from visible output', () => {
  const leakInput = 'Personal Introduction\nMy name is Azizullah Memon.\nValidating implementation against checks.. </thought>\nTask executed successfully.';
  const html = renderMarkdown(leakInput);
  assert.ok(!html.includes('</thought>'), 'orphan closing thought tag leaked');
  assert.ok(!html.includes('<thought>'), 'orphan opening thought tag leaked');
  assert.ok(html.includes('Azizullah Memon'), 'body content preserved');
});

test('inline policy approval card renders with buttons and escapes attributes', () => {
  const approvalInput = '<approval approval-id="appr-test-1" tool="shell_run" scope="pytest tests/">Action requires user confirmation: execute tests</approval>';
  const html = renderMarkdown(approvalInput);
  assert.ok(html.includes('inline-approval-card'), 'approval card class missing');
  assert.ok(html.includes('appr-test-1'), 'approval id missing');
  assert.ok(html.includes('shell_run'), 'tool name missing');
  assert.ok(html.includes('pytest tests/'), 'scope missing');
  assert.ok(html.includes('data-action="approve"'), 'approve button missing');
  assert.ok(html.includes('data-action="deny"'), 'deny button missing');
  assert.ok(!/<(script|img)/i.test(html), 'unsafe tag injected');
});

test('inline math renders math symbols (union, intersection, summation, element of)', () => {
  const mathInput = 'The set union is $A \\cup B$, intersection is $A \\cap B$, element is $x \\in S$, and summation is $\\sum_{i=1}^n x_i$.';
  const html = renderMarkdown(mathInput);
  assert.ok(html.includes('math-inline'), 'math-inline class missing');
  assert.ok(html.includes('∪'), 'union symbol ∪ missing');
  assert.ok(html.includes('∩'), 'intersection symbol ∩ missing');
  assert.ok(html.includes('∈'), 'element symbol ∈ missing');
  assert.ok(html.includes('∑'), 'summation symbol ∑ missing');
});

test('block math renders display math equations and fractions', () => {
  const blockInput = '$$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$$';
  const html = renderMarkdown(blockInput);
  assert.ok(html.includes('math-block'), 'math-block container missing');
  assert.ok(html.includes('∑'), 'summation symbol missing in block');
  assert.ok(html.includes('data-raw'), 'data-raw attribute missing');
});

test('bracket-style inline \\( \\) and display math \\[ \\] render properly', () => {
  const inlineInput = 'Let \\(A \\cup B\\) denote the union and \\(A \\cap B\\) denote the intersection.';
  const inlineHtml = renderMarkdown(inlineInput);
  assert.ok(inlineHtml.includes('math-inline'), 'inline math class missing');
  assert.ok(inlineHtml.includes('∪'), 'union symbol ∪ missing in bracket format');
  assert.ok(inlineHtml.includes('∩'), 'intersection symbol ∩ missing in bracket format');

  const blockInput = '\\[\\boxed{A \\cup B = \\{x \\mid x \\in A \\text{ or } x \\in B\\}}\\]';
  const blockHtml = renderMarkdown(blockInput);
  assert.ok(blockHtml.includes('math-block'), 'math-block container missing for bracket display');
  assert.ok(blockHtml.includes('∪'), 'union symbol missing in bracket display');
  assert.ok(blockHtml.includes('∈'), 'element symbol missing in bracket display');
});

test('math rendering is XSS-safe against script and image injections', () => {
  const mathPayload = '$<script>alert(1)</script>$ and $$<img src=x onerror=alert(2)>$$';
  const html = renderMarkdown(mathPayload);
  assert.ok(!/<script/i.test(html), 'script tag injected in math');
  assert.ok(!/<img/i.test(html), 'img tag injected in math');
  assert.ok(html.includes('&lt;script&gt;'), 'script tag was not escaped');
});

test('aligned environment in block math cleans up raw tags and produces clean line breaks', () => {
  const alignedInput = '\\[\\begin{aligned} A \\cup B &= \\{1, 2, 3\\} \\\\ &= \\{x \\mid x \\in A\\} \\end{aligned}\\]';
  const html = renderMarkdown(alignedInput);
  const displayMatch = html.match(/<span class="math-display">([\s\S]*?)<\/span>/);
  assert.ok(displayMatch, 'math-display span missing');
  assert.ok(!displayMatch[1].includes('\\begin{aligned}'), 'raw begin aligned leaked in display');
  assert.ok(!displayMatch[1].includes('\\end{aligned}'), 'raw end aligned leaked in display');
  assert.ok(displayMatch[1].includes('∪'), 'union symbol missing');
  assert.ok(displayMatch[1].includes('<br>'), 'line break missing');
});

test('inline code badge with ASCII set union normalizes to unicode union', () => {
  const codeInput = 'For sets `A` and `B`, their union is denoted `A U B`.';
  const html = renderMarkdown(codeInput);
  assert.ok(html.includes('<code>A ∪ B</code>'), 'inline code set union was not normalized');
});




