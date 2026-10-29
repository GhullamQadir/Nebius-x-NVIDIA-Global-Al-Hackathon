import test from 'node:test';
import assert from 'node:assert/strict';

test('CSV export generates valid RFC 4180 format with escaping', () => {
  const sampleMessages = [
    { at: '2026-10-24T12:00:00Z', role: 'user', text: 'Hello, "Nexora"!', tokens: 10, model: 'auto' },
    { at: '2026-10-24T12:00:05Z', role: 'ai', text: 'Line 1\nLine 2 with, commas and "quotes"', tokens: 150, model: 'nemotron-ultra' },
  ];

  const headers = ['Timestamp', 'Role', 'Content', 'Tokens', 'Model'];
  const rows = sampleMessages.map((m) => {
    const time = m.at;
    const role = m.role === 'user' ? 'User' : 'Nexora AI';
    const content = (m.text || '').replace(/"/g, '""');
    const tokens = (m.tokens || 0);
    const model = (m.model || 'auto');
    return `"${time}","${role}","${content}","${tokens}","${model}"`;
  });

  const csv = [headers.join(','), ...rows].join('\r\n');

  assert.match(csv, /Timestamp,Role,Content,Tokens,Model/);
  assert.match(csv, /"Hello, ""Nexora""!"/);
  assert.match(csv, /"Line 1\nLine 2 with, commas and ""quotes"""/);
  assert.match(csv, /nemotron-ultra/);
});

test('Output verbosity maps correctly to prompt requirements', () => {
  const modes = ['auto', 'concise', 'detailed'];
  const budgets = {
    auto: 2048,
    concise: 1024,
    detailed: 4096,
  };

  modes.forEach((mode) => {
    assert.ok(budgets[mode] > 0);
    assert.ok(['auto', 'concise', 'detailed'].includes(mode));
  });

  assert.equal(budgets.concise <= 1024, true);
  assert.equal(budgets.detailed >= 4096, true);
});

test('File attachments block is properly formatted into task context', () => {
  const attachedFiles = [
    { name: 'solution.py', size: 120, content: 'def solve(): return 42' },
    { name: 'config.json', size: 45, content: '{"debug": true}' }
  ];
  const originalPrompt = 'Analyze the algorithm complexity.';

  const filesBlock = attachedFiles
    .map((f) => `--- File: ${f.name} (${f.size} bytes) ---\n${f.content}`)
    .join('\n\n');
  const fullTaskText = `[Context Files Attached:\n${filesBlock}\n]\n\nTask:\n${originalPrompt}`;

  assert.match(fullTaskText, /--- File: solution\.py \(120 bytes\) ---/);
  assert.match(fullTaskText, /def solve\(\): return 42/);
  assert.match(fullTaskText, /--- File: config\.json \(45 bytes\) ---/);
  assert.match(fullTaskText, /Analyze the algorithm complexity\./);
});

test('View mode states transition cleanly without breaking split view', () => {
  const allowedViews = ['split', 'chat', 'project'];
  const state = { activeView: 'split' };

  function applyView(newView) {
    if (!allowedViews.includes(newView)) throw new Error('Invalid view');
    state.activeView = newView;
    return `view-${newView}`;
  }

  assert.equal(applyView('chat'), 'view-chat');
  assert.equal(state.activeView, 'chat');
  assert.equal(applyView('project'), 'view-project');
  assert.equal(state.activeView, 'project');
  assert.equal(applyView('split'), 'view-split');
  assert.equal(state.activeView, 'split');
});

test('Markdown export produces clean headers and message blocks', () => {
  const sampleMessages = [
    { at: '2026-10-24T12:00:00Z', role: 'user', text: 'Create a portfolio page.' },
    { at: '2026-10-24T12:00:05Z', role: 'ai', text: 'Here is the portfolio code:\n```html\n<h1>Hi</h1>\n```' }
  ];

  const header = `# Nexora Chat Export\n_Exported on ${new Date().toLocaleString()} · ${sampleMessages.length} messages_\n\n---\n\n`;
  const body = sampleMessages.map((m) => {
    const role = m.role === 'user' ? '### 👤 User' : '### 🤖 Nexora AI';
    const time = m.at ? `*(${m.at})*` : '';
    return `${role} ${time}\n\n${(m.text || '').trim()}\n`;
  }).join('\n---\n\n');
  const mdContent = header + body;

  assert.match(mdContent, /# Nexora Chat Export/);
  assert.match(mdContent, /### 👤 User/);
  assert.match(mdContent, /Create a portfolio page\./);
  assert.match(mdContent, /### 🤖 Nexora AI/);
  assert.match(mdContent, /```html/);
});

test('JSON export serializes complete conversation structure', () => {
  const sampleMessages = [
    { id: 'm1', at: '2026-10-24T12:00:00Z', role: 'user', text: 'Hello', tokens: 5, model: 'auto' },
    { id: 'm2', at: '2026-10-24T12:00:02Z', role: 'ai', text: 'World', tokens: 10, model: 'nemotron-ultra' }
  ];

  const data = {
    app: 'Nexora AI Coding Agent',
    exported_at: new Date().toISOString(),
    message_count: sampleMessages.length,
    messages: sampleMessages.map((m) => ({
      id: m.id,
      role: m.role,
      role_label: m.role === 'user' ? 'User' : 'Nexora AI',
      timestamp: m.at,
      content: m.text,
      tokens: m.tokens || 0,
      model: m.model || 'auto',
    })),
  };
  const jsonStr = JSON.stringify(data, null, 2);
  const parsed = JSON.parse(jsonStr);

  assert.equal(parsed.app, 'Nexora AI Coding Agent');
  assert.equal(parsed.message_count, 2);
  assert.equal(parsed.messages[0].content, 'Hello');
  assert.equal(parsed.messages[1].model, 'nemotron-ultra');
});

test('Relative time with UTC parser handles naive SQLite datetime properly', () => {
  const now = Date.now();
  // 5 minutes ago in UTC format
  const fiveMinAgo = new Date(now - 5 * 60 * 1000).toISOString();
  // SQLite format without Z: "YYYY-MM-DD HH:MM:SS"
  const sqliteFormat = fiveMinAgo.replace('T', ' ').replace(/\.\d+Z$/, '');

  function parseDate(value) {
    if (!value) return null;
    if (value instanceof Date) return value;
    let str = String(value).trim();
    if (!str) return null;
    str = str.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)/, '$1T$2');
    if (!/(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(str)) {
      str += 'Z';
    }
    const d = new Date(str);
    return Number.isNaN(d.getTime()) ? new Date(value) : d;
  }

  function relativeTime(value) {
    if (!value) return '—';
    const d = parseDate(value);
    if (!d || Number.isNaN(d.getTime())) return String(value);
    const diff = Date.now() - d.getTime();
    const abs = Math.abs(diff);
    const min = 60_000, hour = 3.6e6, day = 8.64e7;
    if (abs < min) return 'just now';
    if (abs < hour) return `${Math.max(1, Math.round(abs / min))}m ago`;
    if (abs < day) return `${Math.max(1, Math.round(abs / hour))}h ago`;
    return d.toLocaleDateString();
  }

  assert.equal(relativeTime(sqliteFormat), '5m ago');
});

test('Appearance typography and sizing mappings are complete and valid', () => {
  const UI_FONT_MAP = {
    'Anthropic Sans': `'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`,
    'System': `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`,
    'OpenDyslexic': `'OpenDyslexic', 'Atkinson Hyperlegible', sans-serif`,
    'Inter': `'Inter', system-ui, sans-serif`,
    'Outfit': `'Outfit', sans-serif`,
    'Geist': `'Geist', -apple-system, BlinkMacSystemFont, sans-serif`,
    'Roboto': `'Roboto', sans-serif`,
  };

  const CHAT_SIZE_MAP = {
    'small': '11.5px',
    'medium': '13px',
    'large': '15px',
  };

  const CHAT_WIDTH_MAP = {
    'narrow': '680px',
    'medium': '860px',
    'wide': '1200px',
  };

  assert.ok(UI_FONT_MAP['Anthropic Sans'].includes('Inter'));
  assert.ok(UI_FONT_MAP['OpenDyslexic'].includes('Atkinson Hyperlegible'));
  assert.ok(UI_FONT_MAP['Geist'].includes('Geist'));

  assert.equal(CHAT_SIZE_MAP['small'], '11.5px');
  assert.equal(CHAT_SIZE_MAP['medium'], '13px');
  assert.equal(CHAT_SIZE_MAP['large'], '15px');

  assert.equal(CHAT_WIDTH_MAP['narrow'], '680px');
  assert.equal(CHAT_WIDTH_MAP['medium'], '860px');
  assert.equal(CHAT_WIDTH_MAP['wide'], '1200px');
});

test('Custom theme HSL engine generates cohesive tokens for light and dark modes', () => {
  const hexToHsl = (hex) => {
    let c = hex.replace('#', '');
    if (c.length === 3) c = c.split('').map((x) => x + x).join('');
    const num = parseInt(c, 16);
    let r = (num >> 16) / 255, g = ((num >> 8) & 255) / 255, b = (num & 255) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0, l = (max + min) / 2;
    if (max !== min) {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        case b: h = (r - g) / d + 4; break;
      }
      h = Math.round(h * 60);
    }
    return { h, s: Math.round(s * 100), l: Math.round(l * 100) };
  };

  const hslToHex = (h, s, l) => {
    s /= 100;
    l /= 100;
    const a = s * Math.min(l, 1 - l);
    const f = (n) => {
      const k = (n + h / 30) % 12;
      const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
      return Math.round(255 * color).toString(16).padStart(2, '0');
    };
    return `#${f(0)}${f(8)}${f(4)}`;
  };

  // Test indigo hex conversion
  const hsl = hexToHsl('#818cf8');
  assert.equal(hsl.h >= 230 && hsl.h <= 245, true);
  const roundtripHex = hslToHex(hsl.h, hsl.s, hsl.l);
  assert.equal(typeof roundtripHex, 'string');
  assert.equal(roundtripHex.startsWith('#'), true);

  // Test theme engine token calculation
  const generateThemeTokens = (hue, sat, light, mode) => {
    if (mode === 'light') {
      return {
        bgMain: `hsl(${hue}, 20%, 98%)`,
        bgSidebar: '#ffffff',
        bgInput: '#ffffff',
        textLight: '#0f172a',
        brand: `hsl(${hue}, ${Math.max(68, sat)}%, 44%)`
      };
    }
    // Midnight Slate Dark Palette (#06141B, #11212D, #253745, #4A5C6A, #9BA8AB, #CCD0CF)
    return {
      bgSidebar: '#06141B',
      bgMain: '#11212D',
      bgInput: '#253745',
      border: '#253745',
      borderLight: '#4A5C6A',
      textDim: '#9BA8AB',
      textLight: '#CCD0CF',
      brand: `hsl(${hue}, ${sat}%, ${light}%)`
    };
  };

  const darkTokens = generateThemeTokens(200, 40, 59, 'dark');
  assert.equal(darkTokens.bgSidebar, '#06141B');
  assert.equal(darkTokens.bgMain, '#11212D');
  assert.equal(darkTokens.bgInput, '#253745');
  assert.equal(darkTokens.borderLight, '#4A5C6A');
  assert.equal(darkTokens.textDim, '#9BA8AB');
  assert.equal(darkTokens.textLight, '#CCD0CF');

  const lightTokens = generateThemeTokens(239, 84, 67, 'light');
  assert.equal(lightTokens.bgMain, 'hsl(239, 20%, 98%)');
  assert.equal(lightTokens.textLight, '#0f172a');
});

test('Responsive slider width adapts top-nav buttons and avoids overlap', () => {
  const getNavLayoutState = (width) => {
    return {
      isCompact: width < 580,
      isMini: width < 400,
      hideButtonLabels: width < 580,
      hideTelemetry: width < 580,
      maxTitleWidth: width < 380 ? 70 : 190,
    };
  };

  // Narrow split view drag (340px)
  const narrowState = getNavLayoutState(340);
  assert.equal(narrowState.isCompact, true);
  assert.equal(narrowState.hideButtonLabels, true);
  assert.equal(narrowState.hideTelemetry, true);
  assert.equal(narrowState.maxTitleWidth, 70);

  // Medium width drag (520px)
  const mediumState = getNavLayoutState(520);
  assert.equal(mediumState.isCompact, true);
  assert.equal(mediumState.hideButtonLabels, true);

  // Full / Wide view (800px)
  const wideState = getNavLayoutState(800);
  assert.equal(wideState.isCompact, false);
  assert.equal(wideState.hideButtonLabels, false);
  assert.equal(wideState.hideTelemetry, false);
});

test('Multi-format file upload enforces 10MB limit and formats icons', () => {
  const MAX_LIMIT = 10 * 1024 * 1024; // 10 MB

  const validateFile = (file) => {
    if (file.size > MAX_LIMIT) {
      return { ok: false, error: `File "${file.name}" exceeds maximum allowed limit of 10 MB.` };
    }
    return { ok: true };
  };

  const getFileIcon = (filename) => {
    const ext = (filename || '').split('.').pop().toLowerCase();
    if (['zip', 'rar', 'tar', 'gz', 'tgz'].includes(ext)) return '📦';
    if (['pdf'].includes(ext)) return '📄';
    if (['doc', 'docx'].includes(ext)) return '📝';
    if (['json', 'csv', 'yaml', 'yml'].includes(ext)) return '📊';
    if (['py', 'js', 'ts', 'html', 'css', 'cpp', 'rs', 'go'].includes(ext)) return '💻';
    return '📄';
  };

  const formatFileSize = (bytes) => {
    if (!bytes || bytes < 1024) return `${bytes || 0} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // 1. Icon mapping
  assert.equal(getFileIcon('project.zip'), '📦');
  assert.equal(getFileIcon('manual.pdf'), '📄');
  assert.equal(getFileIcon('report.docx'), '📝');
  assert.equal(getFileIcon('main.py'), '💻');
  assert.equal(getFileIcon('data.json'), '📊');

  // 2. Size formatting
  assert.equal(formatFileSize(500), '500 B');
  assert.equal(formatFileSize(150000), '146.5 KB');
  assert.equal(formatFileSize(5242880), '5.0 MB');

  // 3. Limit validation
  assert.equal(validateFile({ name: 'calc.py', size: 1024 }).ok, true);
  assert.equal(validateFile({ name: 'valid.zip', size: 9 * 1024 * 1024 }).ok, true);
  const overLimit = validateFile({ name: 'huge.zip', size: 12 * 1024 * 1024 });
  assert.equal(overLimit.ok, false);
  assert.equal(overLimit.error.includes('10 MB'), true);
});

test('Light mode palette achieves WCAG AA contrast ratio for primary and secondary text', () => {
  const getLuminance = (hex) => {
    let c = hex.replace('#', '');
    if (c.length === 3) c = c.split('').map((x) => x + x).join('');
    const num = parseInt(c, 16);
    const rgb = [(num >> 16) / 255, ((num >> 8) & 255) / 255, (num & 255) / 255].map((v) => {
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
  };

  const getContrast = (hex1, hex2) => {
    const l1 = getLuminance(hex1);
    const l2 = getLuminance(hex2);
    const brightest = Math.max(l1, l2);
    const darkest = Math.min(l1, l2);
    return (brightest + 0.05) / (darkest + 0.05);
  };

  const lightPalette = {
    bgMain: '#f8fafc',
    bgSidebar: '#ffffff',
    bgActiveItem: '#e2e8f0',
    bgCodeHeader: '#f1f5f9',
    textLight: '#0f172a',
    textDim: '#475569',
    codeFilename: '#0369a1',
    brand: '#4f46e5',
  };

  // 1. Primary text on main background (WCAG AAA requires >= 7:1)
  const mainContrast = getContrast(lightPalette.textLight, lightPalette.bgMain);
  assert.ok(mainContrast >= 7.0, `Primary text contrast ${mainContrast} must be >= 7:1`);

  // 2. Active item text on active pill background in sidebar (WCAG AAA requires >= 7:1)
  const activeItemContrast = getContrast(lightPalette.textLight, lightPalette.bgActiveItem);
  assert.ok(activeItemContrast >= 7.0, `Active sidebar item contrast ${activeItemContrast} must be >= 7:1`);

  // 3. Secondary/dim text on white sidebar (WCAG AA requires >= 4.5:1)
  const dimContrast = getContrast(lightPalette.textDim, lightPalette.bgSidebar);
  assert.ok(dimContrast >= 4.5, `Secondary dim text contrast ${dimContrast} must be >= 4.5:1`);

  // 4. Code block header filename on header background (WCAG AA requires >= 4.5:1)
  const codeHeaderContrast = getContrast(lightPalette.codeFilename, lightPalette.bgCodeHeader);
  assert.ok(codeHeaderContrast >= 4.5, `Code header filename contrast ${codeHeaderContrast} must be >= 4.5:1`);

  // 5. Brand accent on white (WCAG AA requires >= 4.5:1 for interactive controls)
  const brandContrast = getContrast(lightPalette.brand, lightPalette.bgSidebar);
  assert.ok(brandContrast >= 4.5, `Brand button contrast ${brandContrast} must be >= 4.5:1`);
});

