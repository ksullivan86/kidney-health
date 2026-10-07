#!/usr/bin/env node
// Runs the browser twin of the AI guard's blocklist (app/static/js/engine/aiguard.js) on texts from stdin:
//
//   echo '["Take 6 units", "Pumpkin soup"]' | node tests/js/aiguard_twin.mjs
//   → {"source": "...", "confusables": {...}, "mask": "[hidden]", "blocked": [...], "masked": [...]}
//
// tests/test_ai_guard_twin.py compares the answers with app/ai/guard.py.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const FILE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'app', 'static', 'js', 'engine', 'aiguard.js');
const context = vm.createContext({});
vm.runInContext('globalThis.window = globalThis;', context);
vm.runInContext(readFileSync(FILE, 'utf8'), context, { filename: 'aiguard.js' });
const G = vm.runInContext('globalThis.KH.aiguard', context);
const texts = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({
  source: G.BLOCKLIST_SOURCE,
  confusables: { ...G.CONFUSABLES },
  mask: G.MASK,
  blocked: texts.map((t) => G.blocked(t)),
  masked: texts.map((t) => G.maskForDisplay(t)),
}));
