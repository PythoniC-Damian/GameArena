/* Rotate hero and game-card artwork without downloading every image at once. */
(() => {
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = false;
  const instances = [];
  document.querySelectorAll('[data-carousel]').forEach(root => {
    const slides = Array.from(root.querySelectorAll('.ga-slide'));
    if (!slides.length) return;
    const dots = Array.from(root.querySelectorAll('[data-slide]'));
    let index = 0, timer, visible = false, hovering = false, startX;
    function load(slide) {
      const img = slide.matches('img') ? slide : slide.querySelector('img');
      if (img?.dataset.src) { if (img.dataset.srcset) { img.srcset = img.dataset.srcset; delete img.dataset.srcset; } img.src = img.dataset.src; delete img.dataset.src; }
    }
    function show(next) {
      index = (next + slides.length) % slides.length;
      load(slides[index]);
      if (visible && !motion.matches && document.body.dataset.reduceMotion !== 'true') load(slides[(index + 1) % slides.length]);
      slides.forEach((slide, i) => {
        slide.classList.toggle('is-active', i === index);
        if (slide.matches('img')) slide.setAttribute('aria-hidden', 'true');
      });
      dots.forEach((dot, i) => dot.setAttribute('aria-current', String(i === index)));
      const title = root.querySelector('[data-carousel-title]');
      if (title) title.textContent = slides[index].dataset.title;
    }
    function restart() {
      clearInterval(timer);
      if (slides.length > 1 && visible && !hovering && !paused && !document.hidden && !motion.matches && document.body.dataset.reduceMotion !== 'true' && !root.contains(document.activeElement)) {
        timer = setInterval(() => show(index + 1, 1), Number(root.dataset.interval) || 6000);
      }
    }
    root.querySelector('[data-prev]')?.addEventListener('click', () => show(index - 1, -1));
    root.querySelector('[data-next]')?.addEventListener('click', () => show(index + 1, 1));
    dots.forEach((dot, i) => dot.addEventListener('click', () => show(i)));
    root.addEventListener('mouseenter', () => { hovering = true; restart(); });
    root.addEventListener('mouseleave', () => { hovering = false; restart(); });
    root.addEventListener('focusin', restart);
    root.addEventListener('focusout', () => setTimeout(restart, 0));
    root.addEventListener('touchstart', event => { startX = event.changedTouches[0].clientX; clearInterval(timer); }, {passive:true});
    root.addEventListener('touchend', event => {
      const distance = event.changedTouches[0].clientX - startX;
      if (Math.abs(distance) > 40) show(index + (distance < 0 ? 1 : -1), distance < 0 ? 1 : -1);
      restart();
    }, {passive:true});
    if ('IntersectionObserver' in window) new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (visible && !motion.matches) load(slides[(index + 1) % slides.length]); restart(); }, {threshold:0.1}).observe(root);
    else visible = true;
    document.addEventListener('visibilitychange', restart);
    motion.addEventListener('change', restart);

    show(0, 0); restart(); instances.push(restart);
  });
  document.querySelectorAll('[data-pause]').forEach(button => button.addEventListener('click', () => {
    paused = !paused;
    document.querySelectorAll('[data-pause]').forEach(control => {
      control.setAttribute('aria-pressed', String(paused));
      control.setAttribute('aria-label', `${paused ? 'Resume' : 'Pause'} image carousels`);
      control.textContent = paused ? '▷' : 'Ⅱ';
    });
    instances.forEach(restart => restart());
  }));
})();
