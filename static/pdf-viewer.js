'use strict';
// In-app PDF viewer for vouchers. A plain link replaces the whole home-screen
// app on the iPhone with the PDF and leaves no way back; this overlay keeps a
// "Zurück" button, and the back gesture closes it too.
// Used by the app and the offline page: links with data-pdf open here.

let pdfViewerPushed = false;

function pdfViewerClose(fromHistory = false) {
  const viewer = document.querySelector('#pdf-viewer');
  if (!viewer) return;
  viewer.remove();
  document.body.classList.remove('pdf-open');
  if (pdfViewerPushed && !fromHistory) history.back();
  pdfViewerPushed = false;
}

function pdfViewerOpen(url, title) {
  pdfViewerClose();
  const viewer = document.createElement('div');
  viewer.id = 'pdf-viewer';
  viewer.className = 'pdf-viewer';
  viewer.setAttribute('role', 'dialog');
  viewer.setAttribute('aria-modal', 'true');
  viewer.setAttribute('aria-label', title);
  const bar = document.createElement('div');
  bar.className = 'pdf-bar';
  const back = document.createElement('button');
  back.type = 'button';
  back.className = 'btn';
  back.textContent = '‹ Zurück';
  back.addEventListener('click', () => pdfViewerClose());
  const label = document.createElement('b');
  label.textContent = title;
  bar.append(back, label);
  const frame = document.createElement('iframe');
  frame.src = url;
  frame.title = title;
  viewer.append(bar, frame);
  document.body.append(viewer);
  document.body.classList.add('pdf-open');
  back.focus();
  // A history entry lets the iOS back swipe close the viewer instead of the app.
  history.pushState({pdfViewer: true}, '');
  pdfViewerPushed = true;
}

document.addEventListener('click', event => {
  const link = event.target.closest?.('a[data-pdf]');
  if (!link) return;
  event.preventDefault();
  pdfViewerOpen(link.getAttribute('href'), link.dataset.pdf || 'PDF');
});

window.addEventListener('popstate', () => {
  if (document.querySelector('#pdf-viewer')) {
    pdfViewerPushed = false;
    pdfViewerClose(true);
  }
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.querySelector('#pdf-viewer')) pdfViewerClose();
});
