# Stage browser resources

Retrieved 2026-09-28. `SHA256SUMS` pins every included byte. These files are
served only by the STAND_MODE response overlay; source HTML and production
responses continue to use their existing references.

- **Chart.js 4.4.7**: `https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js`, with the package's MIT `LICENSE.md` from the same pinned release.
- **Inter v20**: Google Fonts CSS for `Inter:wght@300;400;500;600;700;800&display=swap` with Chrome 124 User-Agent, and the referenced `fonts.gstatic.com/s/inter/v20/*.woff2` files. SIL OFL 1.1 is in `inter-v20/OFL.txt`.
- **Plus Jakarta Sans v12**: Google Fonts CSS for `Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap` with Chrome 124 User-Agent, and the referenced `fonts.gstatic.com/s/plusjakartasans/v12/*.woff2` files. SIL OFL 1.1 is in `plus-jakarta-sans-v12/OFL.txt`.

Only font URLs inside the two CSS files were changed, to relative local paths.
The exact weight definitions, unicode ranges and font bytes are retained.
