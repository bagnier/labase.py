// Inline rename for todo rows; global for the on* handlers in todo/_list_fragment.html.
window.startEdit = (id) => {
  const span = document.querySelector(`[data-title-id="${id}"]`);
  const form = document.getElementById(`rename-form-${id}`);
  if (!span || !form) return;
  span.classList.add('hidden');
  form.classList.remove('hidden');
  form.classList.add('flex-1');
  const input = form.querySelector('input[name=title]');
  input.focus();
  input.select();
};

window.submitRename = (id) => {
  const form = document.getElementById(`rename-form-${id}`);
  if (form) htmx.trigger(form, 'submit');
};

window.cancelEdit = (id) => {
  const span = document.querySelector(`[data-title-id="${id}"]`);
  const form = document.getElementById(`rename-form-${id}`);
  if (span) span.classList.remove('hidden');
  if (form) form.classList.add('hidden');
};
