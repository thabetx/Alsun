// Shows the address that was asked for. It is put in with textContent, so whatever is written in the address
// can never become html.
const box = document.getElementById("missing-path");
let path = location.pathname + location.search;
try {
  path = decodeURIComponent(path);
} catch (error) {
  // a broken % sequence: the address is shown as it is
}
box.textContent = path.length > 120 ? `${path.slice(0, 120)}…` : path;
