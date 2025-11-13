// UI interactions for improved UX: modal, FAB, toast, better vote/add flows.

const modal = document.getElementById('modal');
const fab = document.getElementById('fab');
const closeModal = document.getElementById('closeModal');
const cancelBtn = document.getElementById('cancelBtn');
const addForm = document.getElementById('addForm');
const itemName = document.getElementById('itemName');
const bubbles = document.getElementById('bubbles');
const toast = document.getElementById('toast');

let isSubmitting = false;

fab.addEventListener('click', () => {
  openModal();
});
closeModal.addEventListener('click', closeModalFn);
cancelBtn.addEventListener('click', closeModalFn);

function openModal(){
  modal.classList.remove('hidden');
  setTimeout(()=> itemName.focus(), 160);
}
function closeModalFn(){
  if(isSubmitting) return;
  modal.classList.add('hidden');
  addForm.reset();
}

/* Toast helper */
let toastTimer = null;
function showToast(msg, ms = 2200){
  clearTimeout(toastTimer);
  toast.textContent = msg;
  toast.classList.remove('hidden');
  toast.style.opacity = '1';
  toastTimer = setTimeout(()=> {
    toast.classList.add('hidden');
  }, ms);
}

/* Fetch items and render */
async function fetchItems(){
  try {
    const res = await fetch('/api/items');
    if (!res.ok) throw new Error('fetch failed');
    const data = await res.json();
    renderBubbles(data);
  } catch (err) {
    console.error(err);
  }
}

/* sizing mapping uses votes but is smooth via transform */
function sizeForVotes(votes){
  const base = 110; // base px for visual badge container
  // using sqrt for smooth growth
  return Math.round(base + Math.sqrt(votes) * 18);
}

function renderBubbles(items){
  bubbles.innerHTML = '';
  items.forEach(it => {
    const el = document.createElement('div');
    el.className = 'bubble';
    // badge size
    const badgeSize = sizeForVotes(it.votes);
    const badge = document.createElement('div');
    badge.className = 'badge';
    badge.style.width = `${Math.min(badgeSize, 160)}px`;
    badge.style.height = `${Math.min(badgeSize, 160)}px`;
    badge.style.borderRadius = `${Math.min(badgeSize, 160)}px`;
    badge.innerHTML = `<span aria-hidden="true">${it.votes}</span>`;

    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = it.name;

    const votes = document.createElement('div');
    votes.className = 'votes';
    votes.textContent = `${it.votes} vote${it.votes === 1 ? '' : 's'}`;

    el.appendChild(badge);
    el.appendChild(name);
    el.appendChild(votes);

    el.onclick = () => vote(it.id, el, badge, votes);

    bubbles.appendChild(el);
  });
}

/* Vote with immediate micro-animation */
async function vote(id, el, badgeEl, votesEl){
  try {
    // optimistic UI micro-grow
    badgeEl.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.16)' }, { transform: 'scale(1)' }], { duration: 320, easing: 'cubic-bezier(.2,.9,.2,1)' });

    const res = await fetch(`/api/items/${id}/vote`, { method: 'POST' });
    if (!res.ok) throw new Error('vote failed');
    const data = await res.json();

    // update specific bubble text (fast)
    votesEl.textContent = `${data.votes} vote${data.votes === 1 ? '' : 's'}`;

    // Animate badge size growth slightly
    const newSize = sizeForVotes(data.votes);
    badgeEl.style.width = `${Math.min(newSize,160)}px`;
    badgeEl.style.height = `${Math.min(newSize,160)}px`;
    badgeEl.style.borderRadius = `${Math.min(newSize,160)}px`;

    showToast('Thanks — your vote is counted!');
    // Occasionally re-fetch to keep ordering consistent
    setTimeout(fetchItems, 600);
  } catch (err) {
    console.error(err);
    showToast('Could not vote. Try reloading.');
  }
}

/* Add item flow */
addForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (isSubmitting) return;
  const name = itemName.value.trim();
  if (!name) return;
  isSubmitting = true;
  document.querySelector('.btn.primary').textContent = 'Adding...';
  try {
    const res = await fetch('/api/items', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ name })
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || 'Failed to add');
      return;
    }
    await res.json();
    closeModalFn();
    showToast('Thanks — item added!');
    fetchItems();
  } catch (err) {
    console.error(err);
    showToast('Could not add item.');
  } finally {
    isSubmitting = false;
    document.querySelector('.btn.primary').textContent = 'Add item';
  }
});

/* initial load and polling */
fetchItems();
setInterval(fetchItems, 4500);
