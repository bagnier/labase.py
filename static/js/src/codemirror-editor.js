import { EditorView, basicSetup } from "codemirror"
import { markdown } from "@codemirror/lang-markdown"

const theme = EditorView.theme({
  "&": { fontSize: "0.875rem", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  ".cm-content": { padding: "0.5rem 0.75rem", minHeight: "16rem" },
  ".cm-focused": { outline: "none" },
  ".cm-scroller": { lineHeight: "1.6" },
})

function applyInline(view, marker, placeholder) {
  const { from, to } = view.state.selection.main
  const selected = view.state.sliceDoc(from, to)
  const text = selected || placeholder
  view.dispatch({
    changes: { from, to, insert: `${marker}${text}${marker}` },
    selection: selected
      ? { anchor: from, head: from + marker.length + text.length + marker.length }
      : { anchor: from + marker.length, head: from + marker.length + text.length },
  })
  view.focus()
}

function applyLinePrefix(view, prefix) {
  const { from } = view.state.selection.main
  const line = view.state.doc.lineAt(from)
  const already = line.text.startsWith(prefix)
  view.dispatch({
    changes: already
      ? { from: line.from, to: line.from + prefix.length, insert: "" }
      : { from: line.from, insert: prefix },
  })
  view.focus()
}

function applyLink(view) {
  const { from, to } = view.state.selection.main
  const selected = view.state.sliceDoc(from, to)
  const text = selected || "texte"
  const insert = `[${text}](url)`
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + text.length + 3, head: from + insert.length - 1 },
  })
  view.focus()
}

function applyImage(view) {
  const { from, to } = view.state.selection.main
  const selected = view.state.sliceDoc(from, to)
  const alt = selected || "alt text"
  const insert = `![${alt}](url)`
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + alt.length + 4, head: from + insert.length - 1 },
  })
  view.focus()
}

function applyTable(view) {
  const { from } = view.state.selection.main
  const insert = `| Column 1 | Column 2 | Column 3 |\n| --- | --- | --- |\n| Cell | Cell | Cell |`
  view.dispatch({ changes: { from, insert } })
  view.focus()
}

function applyCodeBlock(view) {
  const { from, to } = view.state.selection.main
  const selected = view.state.sliceDoc(from, to)
  const text = selected || "code"
  const insert = `\`\`\`\n${text}\n\`\`\``
  view.dispatch({
    changes: { from, to, insert },
    selection: { anchor: from + 4, head: from + 4 + text.length },
  })
  view.focus()
}

const BUTTONS = [
  { icon: "text-b",      title: "Bold",          action: v => applyInline(v, "**", "bold text") },
  { icon: "text-italic", title: "Italic",         action: v => applyInline(v, "*", "italic text") },
  { sep: true },
  { label: "H2",         title: "Heading 2",      action: v => applyLinePrefix(v, "## ") },
  { label: "H3",         title: "Heading 3",      action: v => applyLinePrefix(v, "### ") },
  { sep: true },
  { icon: "link-simple", title: "Link",            action: v => applyLink(v) },
  { icon: "code",        title: "Inline code",     action: v => applyInline(v, "`", "code") },
  { icon: "code-block",  title: "Code block",      action: v => applyCodeBlock(v) },
  { sep: true },
  { icon: "list-bullets",      title: "Bullet list",    action: v => applyLinePrefix(v, "- ") },
  { icon: "list-numbers",      title: "Ordered list",   action: v => applyLinePrefix(v, "1. ") },
  { icon: "check-square",      title: "Task list",      action: v => applyLinePrefix(v, "- [ ] ") },
  { sep: true },
  { icon: "text-strikethrough",title: "Strikethrough",  action: v => applyInline(v, "~~", "strikethrough") },
  { sep: true },
  { icon: "image",             title: "Image",          action: v => applyImage(v) },
  { icon: "table",             title: "Table",          action: v => applyTable(v) },
  { icon: "minus",             title: "Horizontal rule",action: v => { const { from } = v.state.selection.main; v.dispatch({ changes: { from, insert: "\n---\n" } }); v.focus() } },
  { icon: "quotes",            title: "Blockquote",     action: v => applyLinePrefix(v, "> ") },
]

function buildToolbar(view) {
  const bar = document.createElement("div")
  bar.className = "cm-toolbar"
  for (const btn of BUTTONS) {
    if (btn.sep) {
      const sep = document.createElement("span")
      sep.className = "cm-toolbar-sep"
      bar.appendChild(sep)
      continue
    }
    const el = document.createElement("button")
    el.type = "button"
    el.title = btn.title
    el.className = "cm-toolbar-btn"
    if (btn.icon) {
      const icon = document.createElement("i")
      icon.className = `ph ph-${btn.icon} ph-sm`
      el.appendChild(icon)
    } else {
      el.textContent = btn.label
    }
    el.addEventListener("mousedown", e => {
      e.preventDefault()
      btn.action(view)
    })
    bar.appendChild(el)
  }
  return bar
}

window.initMarkdownEditor = function (textarea) {
  const wrapper = document.createElement("div")
  wrapper.className = "cm-wrapper"
  textarea.parentElement.insertBefore(wrapper, textarea)
  textarea.style.display = "none"

  const view = new EditorView({
    doc: textarea.value,
    extensions: [basicSetup, markdown(), theme],
    parent: wrapper,
  })

  wrapper.insertBefore(buildToolbar(view), wrapper.firstChild)

  textarea.closest("form").addEventListener("htmx:configRequest", (e) => {
    e.detail.parameters.content = view.state.doc.toString()
  })
}
