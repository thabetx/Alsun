export function getAllRows() {
  return [...document.querySelectorAll("#block-rows tr.block-row")];
}

export function getRowById(id) {
  return getAllRows().find((tr) => tr.dataset.id === id) ?? null;
}

// the checked rows, in the order of the table (not in the order of the clicks)
export function getSelectedRows() {
  return getAllRows().filter((tr) => tr.querySelector(".block-check").checked);
}
