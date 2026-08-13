// Stanje aplikacije. Malo je, pa je jedan objekat sa pretplatnicima dovoljan.

import { api } from './api.js';

const listeners = new Set();

export const store = {
  settings: {},
  tree: [],
  questionTypes: [],
  stats: {},
  version: '',
  categoryId: null,
  tab: 'pregled',
  expanded: new Set(JSON.parse(localStorage.getItem('expanded') || '[]')),
};

export function subscribe(handler) {
  listeners.add(handler);
  return () => listeners.delete(handler);
}

export function emit() {
  for (const handler of listeners) handler(store);
}

export async function bootstrap() {
  const payload = await api.get('/api/bootstrap');
  store.settings = payload.settings;
  store.tree = payload.tree;
  store.questionTypes = payload.question_types;
  store.stats = payload.stats;
  store.version = payload.version;
  applyTheme(store.settings.theme);
  emit();
  return payload;
}

export async function reloadTree() {
  const payload = await api.get('/api/categories');
  store.tree = payload.tree;
  emit();
}

export async function saveSettings(values) {
  const payload = await api.patch('/api/settings', values);
  store.settings = payload.settings;
  if ('theme' in values) applyTheme(store.settings.theme);
  emit();
  return store.settings;
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark';
}

export function typeLabel(key) {
  const found = store.questionTypes.find((item) => item.key === key);
  return found ? found.label : key;
}

export function findCategory(id, nodes = store.tree) {
  for (const node of nodes) {
    if (node.id === id) return node;
    const deeper = findCategory(id, node.children || []);
    if (deeper) return deeper;
  }
  return null;
}

export function flattenTree(nodes = store.tree, depth = 0, out = []) {
  for (const node of nodes) {
    out.push({ ...node, depth });
    flattenTree(node.children || [], depth + 1, out);
  }
  return out;
}

export function toggleExpanded(id) {
  if (store.expanded.has(id)) store.expanded.delete(id);
  else store.expanded.add(id);
  localStorage.setItem('expanded', JSON.stringify([...store.expanded]));
}

export function expandTo(id) {
  const path = [];
  const walk = (nodes, chain) => {
    for (const node of nodes) {
      if (node.id === id) { path.push(...chain); return true; }
      if (walk(node.children || [], [...chain, node.id])) return true;
    }
    return false;
  };
  walk(store.tree, []);
  path.forEach((item) => store.expanded.add(item));
  localStorage.setItem('expanded', JSON.stringify([...store.expanded]));
}
