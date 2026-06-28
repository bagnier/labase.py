document.body.addEventListener('htmx:afterSwap', (e) => {
  if (e.detail.target?.matches('[data-answer]')) {
    e.detail.target.classList.remove('hidden');
    e.detail.target.closest('.lcard')?.classList.add('revealed');
  }
});

let active = null,
  startX = 0,
  dx = 0;
const THRESHOLD = 110;
document.body.addEventListener('pointerdown', (e) => {
  const card = e.target.closest('.lcard.revealed');
  if (!card || e.target.closest('button')) return;
  active = card;
  startX = e.clientX;
  dx = 0;
});
document.body.addEventListener('pointermove', (e) => {
  if (!active) return;
  dx = e.clientX - startX;
  active.querySelector('.flip').style.transform = `translateX(${dx}px) rotate(${dx / 25}deg)`;
});
document.body.addEventListener('pointerup', () => {
  if (!active) return;
  const card = active;
  active = null;
  const kind = dx > THRESHOLD ? 'learned' : dx < -THRESHOLD ? 'again' : null;
  const flip = card.querySelector('.flip');
  if (!kind) {
    flip.style.transform = '';
    return;
  }
  card.classList.add('flying');
  card.querySelector(`[data-mark="${kind}"]`)?.click();
});
