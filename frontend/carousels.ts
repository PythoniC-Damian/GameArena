import './styles.css';
/* Rotate hero and game-card artwork without downloading every image at once. */
(() => {
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  document.querySelectorAll<HTMLElement>('[data-carousel]').forEach(root => {
    const slides = Array.from(root.querySelectorAll<HTMLElement>('.ga-slide'));
    if (!slides.length) return;
    const dots = Array.from(root.querySelectorAll<HTMLElement>('[data-slide]'));
    let index = 0, visible = false, hovering = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    let startX: number | undefined;
    function load(slide: HTMLElement) {
      const images = slide.matches('img') ? [slide as HTMLImageElement] : Array.from(slide.querySelectorAll<HTMLImageElement>('img'));
      images.forEach(img => {
        if (img.dataset.src) {
          if (img.dataset.srcset) { img.srcset = img.dataset.srcset; delete img.dataset.srcset; }
          img.src = img.dataset.src; delete img.dataset.src;
        }
      });
    }
    function show(next: number) {
      index = (next + slides.length) % slides.length;
      load(slides[index]);
      slides.forEach((slide, i) => {
        slide.classList.toggle('is-active', i === index);
        if (slide.matches('img')) slide.setAttribute('aria-hidden', 'true');
      });
      const firstDot = Math.max(0, Math.min(index - Math.floor(dots.length / 2), slides.length - dots.length));
      dots.forEach((dot, i) => {
        const target = firstDot + i;
        dot.dataset.slide = String(target);
        dot.setAttribute('aria-label', `Show hero image ${target + 1}`);
        dot.setAttribute('aria-current', String(target === index));
      });
      const title = root.querySelector<HTMLElement>('[data-carousel-title]');
      if (title) title.textContent = slides[index].dataset.title || '';
    }
    function restart() {
      clearInterval(timer);
      if (slides.length > 1 && visible && !hovering && !document.hidden && !motion.matches && document.body.dataset.reduceMotion !== 'true' && !root.contains(document.activeElement)) {
        timer = setInterval(() => show(index + 1), Number(root.dataset.interval) || 6000);
      }
    }
    root.querySelector('[data-prev]')?.addEventListener('click', () => show(index - 1));
    root.querySelector('[data-next]')?.addEventListener('click', () => show(index + 1));
    dots.forEach(dot => dot.addEventListener('click', () => show(Number(dot.dataset.slide))));
    root.addEventListener('mouseenter', () => { hovering = true; restart(); });
    root.addEventListener('mouseleave', () => { hovering = false; restart(); });
    root.addEventListener('focusin', restart);
    root.addEventListener('focusout', () => setTimeout(restart, 0));
    root.addEventListener('touchstart', event => { startX = event.changedTouches[0].clientX; clearInterval(timer); }, {passive:true});
    root.addEventListener('touchend', event => {
      if (startX === undefined) return;
      const distance = event.changedTouches[0].clientX - startX;
      if (Math.abs(distance) > 40) show(index + (distance < 0 ? 1 : -1));
      restart();
    }, {passive:true});
    if ('IntersectionObserver' in window) new IntersectionObserver(entries => { visible = entries[0].isIntersecting; restart(); }, {threshold:0.1}).observe(root);
    else visible = true;
    document.addEventListener('visibilitychange', restart);
    motion.addEventListener('change', restart);

    show(0); restart();
  });
})();
