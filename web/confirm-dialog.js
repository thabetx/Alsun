// A confirmation window in the style of the app, instead of the old browser confirm().
// It uses the native <dialog>: the page behind it is blocked, Esc closes it, and the focus stays inside.
// Returns a promise: true if the user confirmed, false for cancel, Esc or a click outside the window.

let openDialog = null;
let closeOpenDialog = null;

export function askConfirmation({
  title,
  message,
  confirmLabel = "متابعة",
  cancelLabel = "إلغاء",
  icon = "fa-circle-question",
  tone = "default", // "danger" for something that can't be undone
}) {
  closeOpenDialog?.(); // only one window at a time

  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "confirm-dialog";
    if (tone === "danger") dialog.classList.add("confirm-danger");
    dialog.setAttribute("aria-labelledby", "confirm-title");
    dialog.setAttribute("aria-describedby", "confirm-message");

    const iconBox = document.createElement("div");
    iconBox.className = "confirm-icon";
    iconBox.innerHTML = `<i class="fa-solid ${icon}" aria-hidden="true"></i>`;

    const heading = document.createElement("h2");
    heading.id = "confirm-title";
    heading.className = "confirm-title";
    heading.textContent = title;

    const text = document.createElement("p");
    text.id = "confirm-message";
    text.className = "confirm-message";
    text.textContent = message;

    const textBox = document.createElement("div");
    textBox.className = "confirm-text";
    textBox.append(heading, text);

    const body = document.createElement("div");
    body.className = "confirm-body";
    body.append(iconBox, textBox);

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "confirm-primary";
    confirmButton.textContent = confirmLabel;

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "confirm-secondary";
    cancelButton.textContent = cancelLabel;

    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    actions.append(confirmButton, cancelButton); // the page is right to left: the main button is on the right

    dialog.append(body, actions);

    // the answer is given right away (not when the browser sends the "close" event)
    let answered = false;
    const answer = (confirmed) => {
      if (answered) return;
      answered = true;
      if (dialog.open) dialog.close();
      dialog.remove();
      if (openDialog === dialog) openDialog = null;
      resolve(confirmed);
    };

    confirmButton.addEventListener("click", () => answer(true));
    cancelButton.addEventListener("click", () => answer(false));
    // a click on the dark area around the window is a cancel
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) answer(false);
    });
    // Esc
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      answer(false);
    });
    dialog.addEventListener("close", () => answer(false));
    closeOpenDialog = () => answer(false);

    document.body.append(dialog);
    openDialog = dialog;
    dialog.showModal();
    confirmButton.focus();
  });
}
