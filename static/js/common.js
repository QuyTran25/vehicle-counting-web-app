
document.getElementById('mobileMenuBtn').addEventListener('click', () => {
  document.getElementById('sidebar').classList.toggle('show');
});
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}
