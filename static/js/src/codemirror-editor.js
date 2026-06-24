import { EditorView, basicSetup } from "codemirror"
import { markdown } from "@codemirror/lang-markdown"

const theme = EditorView.theme({
  "&": { fontSize: "0.875rem", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  ".cm-content": { padding: "0.5rem 0.75rem", minHeight: "16rem" },
  ".cm-focused": { outline: "none" },
  ".cm-scroller": { lineHeight: "1.6" },
})

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

  textarea.closest("form").addEventListener("htmx:configRequest", () => {
    textarea.value = view.state.doc.toString()
  })
}
