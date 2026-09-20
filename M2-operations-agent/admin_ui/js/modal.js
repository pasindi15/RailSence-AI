// Shared modal helper.

function openModal(title, bodyHtml, onSave, saveLabel = "Save") {
  const overlay = document.getElementById("modal-overlay");
  overlay.innerHTML = `
    <div class="modal">
      <h3>${title}</h3>
      <div id="modal-body">${bodyHtml}</div>
      <div class="modal-actions">
        <button class="btn btn-ghost" id="modal-cancel">Cancel</button>
        <button class="btn btn-primary" id="modal-save">${saveLabel}</button>
      </div>
    </div>
  `;
  overlay.classList.add("visible");
  document.getElementById("modal-cancel").onclick = closeModal;
  document.getElementById("modal-save").onclick = async () => {
    const btn = document.getElementById("modal-save");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      await onSave();
    } finally {
      btn.disabled = false;
      btn.textContent = saveLabel;
    }
  };
}

function closeModal() {
  document.getElementById("modal-overlay").classList.remove("visible");
  document.getElementById("modal-overlay").innerHTML = "";
}

// Object-style API used by the officer/RBAC views. Unlike openModal() it adds no
// footer buttons: callers pass markup that already contains its own .modal-actions.
const Modal = {
  open({ title = "", html = "" } = {}) {
    const overlay = document.getElementById("modal-overlay");
    if (!overlay) return;
    overlay.innerHTML = `
      <div class="modal">
        <h3>${title}</h3>
        <div id="modal-body">${html}</div>
      </div>
    `;
    overlay.classList.add("visible");
    const firstField = overlay.querySelector("input, select, textarea");
    if (firstField) firstField.focus();
  },
  close: closeModal,
};

document.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("modal-overlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeModal();
    });
  }
});
