import { markdown } from '@codemirror/lang-markdown';
import { basicSetup, EditorView } from 'codemirror';

const theme = EditorView.theme({
  '&': { fontSize: '0.875rem', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' },
  '.cm-content': { padding: '0.5rem 0.75rem', minHeight: '16rem' },
  '.cm-focused': { outline: 'none' },
  '.cm-scroller': { lineHeight: '1.6' },
});

function applyInline(view, marker, placeholder) {
  const { from, to } = view.state.selection.main;
  const selected = view.state.sliceDoc(from, to);
  const text = selected || placeholder;
  view.dispatch({
    changes: { from, to, insert: `${marker}${text}${marker}` },
    selection: selected
      ? { anchor: from, head: from + marker.length + text.length + marker.length }
      : { anchor: from + marker.length, head: from + marker.length + text.length },
  });
  view.focus();
}

function applyLinePrefix(view, prefix) {
  const { from } = view.state.selection.main;
  const line = view.state.doc.lineAt(from);
  const already = line.text.startsWith(prefix);
  view.dispatch({
    changes: already
      ? { from: line.from, to: line.from + prefix.length, insert: '' }
      : { from: line.from, insert: prefix },
  });
  view.focus();
}

// Insert a Markdown link (`lead` = "[") or image (`lead` = "![") wrapping the selection
// (or `placeholder`), leaving the "url" part selected for the user to type over.
function applyLinkLike(view, lead, placeholder) {
  const { from, to } = view.state.selection.main;
  const selected = view.state.sliceDoc(from, to);
  const text = selected || placeholder;
  const insert = `${lead}${text}](url)`;
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + lead.length + text.length + 2, head: from + insert.length - 1 },
  });
  view.focus();
}

function applyLink(view) {
  applyLinkLike(view, '[', 'texte');
}

function applyImage(view) {
  applyLinkLike(view, '![', 'alt text');
}

function replaceText(view, needle, replacement) {
  const idx = view.state.doc.toString().indexOf(needle);
  if (idx >= 0)
    view.dispatch({ changes: { from: idx, to: idx + needle.length, insert: replacement } });
}

// Upload an image to the org's file storage (the files app) and embed it as Markdown.
function uploadImage(view, uploadUrl) {
  if (!uploadUrl) return applyImage(view);
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    const placeholder = `![uploading ${file.name}…]()`;
    const { from, to } = view.state.selection.main;
    view.dispatch({ changes: { from, to, insert: placeholder } });
    view.focus();
    try {
      const body = new FormData();
      body.append('file', file);
      const res = await fetch(uploadUrl, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        body,
      });
      if (!res.ok) throw new Error(`upload failed: ${res.status}`);
      const data = await res.json();
      replaceText(view, placeholder, `![${file.name}](${data.url})`);
    } catch {
      replaceText(view, placeholder, '');
      alert('Image upload failed.');
    }
  });
  input.click();
}

function applyTable(view) {
  const { from } = view.state.selection.main;
  const insert = `| Column 1 | Column 2 | Column 3 |\n| --- | --- | --- |\n| Cell | Cell | Cell |`;
  view.dispatch({ changes: { from, insert } });
  view.focus();
}

function applyCodeBlock(view) {
  const { from, to } = view.state.selection.main;
  const selected = view.state.sliceDoc(from, to);
  const text = selected || 'code';
  const insert = `\`\`\`\n${text}\n\`\`\``;
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + 4, head: from + 4 + text.length },
  });
  view.focus();
}

const BUTTONS = [
  { icon: 'text-b', title: 'Bold', action: (v) => applyInline(v, '**', 'bold text') },
  { icon: 'text-italic', title: 'Italic', action: (v) => applyInline(v, '*', 'italic text') },
  { sep: true },
  { label: 'H2', title: 'Heading 2', action: (v) => applyLinePrefix(v, '## ') },
  { label: 'H3', title: 'Heading 3', action: (v) => applyLinePrefix(v, '### ') },
  { sep: true },
  { icon: 'link-simple', title: 'Link', action: (v) => applyLink(v) },
  { icon: 'code', title: 'Inline code', action: (v) => applyInline(v, '`', 'code') },
  { icon: 'code-block', title: 'Code block', action: (v) => applyCodeBlock(v) },
  { sep: true },
  { icon: 'list-bullets', title: 'Bullet list', action: (v) => applyLinePrefix(v, '- ') },
  { icon: 'list-numbers', title: 'Ordered list', action: (v) => applyLinePrefix(v, '1. ') },
  { icon: 'check-square', title: 'Task list', action: (v) => applyLinePrefix(v, '- [ ] ') },
  { sep: true },
  {
    icon: 'text-strikethrough',
    title: 'Strikethrough',
    action: (v) => applyInline(v, '~~', 'strikethrough'),
  },
  { sep: true },
  { icon: 'image', title: 'Upload image', action: (v, ctx) => uploadImage(v, ctx.uploadUrl) },
  { icon: 'table', title: 'Table', action: (v) => applyTable(v) },
  {
    icon: 'minus',
    title: 'Horizontal rule',
    action: (v) => {
      const { from } = v.state.selection.main;
      v.dispatch({ changes: { from, insert: '\n---\n' } });
      v.focus();
    },
  },
  { icon: 'quotes', title: 'Blockquote', action: (v) => applyLinePrefix(v, '> ') },
];

function buildToolbar(view, ctx) {
  const bar = document.createElement('div');
  bar.className = 'cm-toolbar';
  for (const btn of BUTTONS) {
    if (btn.sep) {
      const sep = document.createElement('span');
      sep.className = 'cm-toolbar-sep';
      bar.appendChild(sep);
      continue;
    }
    const el = document.createElement('button');
    el.type = 'button';
    el.title = btn.title;
    el.setAttribute('aria-label', btn.title);
    el.className = 'cm-toolbar-btn';
    if (btn.icon) {
      const icon = document.createElement('i');
      icon.className = `ph ph-${btn.icon} ph-sm`;
      el.appendChild(icon);
    } else {
      el.textContent = btn.label;
    }
    el.addEventListener('mousedown', (e) => {
      e.preventDefault();
      btn.action(view, ctx);
    });
    bar.appendChild(el);
  }
  return bar;
}

window.initMarkdownEditor = (textarea) => {
  const wrapper = document.createElement('div');
  wrapper.className = 'cm-wrapper';
  textarea.parentElement.insertBefore(wrapper, textarea);
  textarea.style.display = 'none';

  const view = new EditorView({
    doc: textarea.value,
    extensions: [basicSetup, markdown(), theme],
    parent: wrapper,
  });

  const ctx = { uploadUrl: textarea.dataset.uploadUrl || '' };
  wrapper.insertBefore(buildToolbar(view, ctx), wrapper.firstChild);

  textarea.closest('form').addEventListener('htmx:configRequest', (e) => {
    e.detail.parameters.content = view.state.doc.toString();
  });
};
