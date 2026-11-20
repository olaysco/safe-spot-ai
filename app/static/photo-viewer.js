'use strict';
(() => {
  const dialog = document.getElementById('photo-viewer');
  const image = document.getElementById('photo-viewer-image');
  let trigger = null, previousOverflow = '';
  document.addEventListener('click', event => {
    const target = event.target.closest('[data-photo-expand], .attachment-grid a');
    if (!target) return;
    const thumbnail = target.querySelector('img');
    if (!thumbnail) return;
    event.preventDefault();
    trigger = target;
    image.src = target.dataset.photoExpand || target.href;
    image.alt = thumbnail.alt || 'Evidence photo';
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.showModal();
  });
  document.getElementById('close-photo-viewer').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => {
    document.body.style.overflow = previousOverflow;
    image.removeAttribute('src');
    image.alt = '';
    (trigger?.isConnected ? trigger : document.getElementById('main'))?.focus({preventScroll: true});
    trigger = null;
  });
})();
