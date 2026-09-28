// Renders the PNG app icons from static/icons/icon.svg with the preinstalled
// Chromium (Playwright). iOS needs an opaque, square PNG as apple-touch-icon;
// it rounds the corners itself.
//   PW=/path/to/playwright node scripts/render_icons.cjs
const { chromium } = require(process.env.PW || 'playwright');
const fs = require('node:fs');

const SIZES = {'apple-touch-icon.png': 180, 'icon-192.png': 192, 'icon-512.png': 512};

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? {executablePath: process.env.CHROMIUM} : {});
  const svg = fs.readFileSync('static/icons/icon.svg', 'utf8');
  for (const [name, size] of Object.entries(SIZES)) {
    const page = await browser.newPage({viewport: {width: size, height: size}});
    await page.setContent(`<body style="margin:0">${svg.replace('<svg ', `<svg width="${size}" height="${size}" `)}</body>`);
    await page.screenshot({path: 'static/icons/' + name});
    await page.close();
  }
  await browser.close();
})();
