# PageSpeed refinements - 12 October 2026

The supplied desktop report scores 98 Performance and 100 Accessibility, Best Practices and SEO. FCP is 0.2s, LCP 0.4s, TBT 0ms, CLS 0.005 and Speed Index 1.5s. It reports no field data. The desktop estimates are 120ms render blocking, 48KiB cache lifetime savings and 18KiB image delivery savings. These are the original report's estimates, not measured gains from this patch.

Report: https://pagespeed.web.dev/analysis/https-gamearena01-com/xq3rjfg0j6?form_factor=desktop

- Fallback CSS is combined in the existing cascade order into one fingerprinted site.css, reducing five blocking stylesheet requests to one without delaying essential styling. Run python scripts/build_styles.py after editing styles. Runtime source-digest checking falls back to individual styles if the bundle is stale/missing, so local CSS edits remain visible. The digest normalizes Windows/Linux line endings. The Render build also regenerates the bundle; the current generated bundle is committed so it works with the existing dashboard build command. The optional Vite branch retains its current behavior.
- Responsive images now use a manifest of actual pixel widths and a separately computed fingerprint for each candidate. Replacing only the width in an image URL previously retained the larger file's fingerprint, defeating immutable caching. The new variants close the resolution gaps with 384, 640, 768 and 1200 widths, plus source-native caps where needed. efootball_2 is only 1024px wide and is labelled correctly rather than advertised as 1440px.
- python scripts/optimize_images.py --only-new retains existing optimized files and original artwork, creates additional size derivatives, and writes the exact-width manifest. No colors, layouts or image subject matter are changed.
- App-icon URLs are fingerprinted for long-lived caching; the manifest and service worker remain revalidated. Authenticated HTML stays private/no-store.

The changes do not claim to eliminate every forced-reflow, DOM or layout-shift audit. New PageSpeed results must be measured after deployment; the report above will continue to show the old run.
