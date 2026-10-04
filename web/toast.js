let hideTimer = null;

export function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.toggle("toast-error", isError);
  toast.hidden = false;
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => { toast.hidden = true; }, 4500);
}
