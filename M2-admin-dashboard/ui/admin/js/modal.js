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

document.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("modal-overlay");
  if (overlay) {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeModal();
    });
  }
});
