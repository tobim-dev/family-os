'use strict';
// Pull to refresh: iOS home-screen apps have no built-in pull to refresh.
// Dragging down at the top of the page reloads the current view.

const PULL_THRESHOLD = 70;   // px of finger movement (damped) to trigger
let pullStart = null, pullDistance = 0, pullBusy = false;

function pullIndicator() {
  let el = document.querySelector('#pull-refresh');
  if (!el) {
    el = document.createElement('div');
    el.id = 'pull-refresh';
    el.className = 'pull-refresh';
    el.setAttribute('aria-live', 'polite');
    el.innerHTML = '<span class="pull-spinner" aria-hidden="true"></span><span class="pull-text"></span>';
    document.body.append(el);
  }
  return el;
}

function pullShow(distance, text, busy = false) {
  const el = pullIndicator();
  el.style.setProperty('--pull', `${Math.min(distance, PULL_THRESHOLD + 20)}px`);
  el.classList.toggle('visible', distance > 8 || busy);
  el.classList.toggle('ready', distance >= PULL_THRESHOLD);
  el.classList.toggle('busy', busy);
  el.querySelector('.pull-text').textContent = text;
}

// Reload shared data and whatever the current view loads on its own.
async function refreshView() {
  await load();
  if (view === 'meals' && typeof loadMeals === 'function') await loadMeals();
  if (view === 'nanny' && typeof loadNanny === 'function') await loadNanny();
  if (view === 'lina' && typeof loadLina === 'function') await loadLina();
}

function pullAllowed(target) {
  if (!state || pullBusy || modal.open || window.scrollY > 0) return false;
  // Do not hijack scrolling inside lists that scroll on their own.
  for (let el = target; el && el !== document.body; el = el.parentElement) {
    if (el.scrollTop > 0) return false;
  }
  return true;
}

window.addEventListener('touchstart', event => {
  pullStart = pullAllowed(event.target) && event.touches.length === 1 ? event.touches[0].clientY : null;
  pullDistance = 0;
}, {passive: true});

window.addEventListener('touchmove', event => {
  if (pullStart === null) return;
  const delta = event.touches[0].clientY - pullStart;
  if (delta <= 0 || window.scrollY > 0) {
    pullStart = null;
    pullShow(0, '');
    return;
  }
  pullDistance = delta * 0.5;  // resistance, like native pull to refresh
  pullShow(pullDistance, pullDistance >= PULL_THRESHOLD ? 'Loslassen zum Aktualisieren' : 'Zum Aktualisieren ziehen');
}, {passive: true});

window.addEventListener('touchend', async () => {
  if (pullStart === null) return;
  pullStart = null;
  if (pullDistance < PULL_THRESHOLD) {
    pullShow(0, '');
    return;
  }
  pullBusy = true;
  pullShow(PULL_THRESHOLD, 'Wird aktualisiert …', true);
  try {
    await refreshView();
    pullShow(0, '');
  } catch (error) {
    pullShow(0, '');
    toast(error.message);
  } finally {
    pullBusy = false;
    pullDistance = 0;
  }
});
