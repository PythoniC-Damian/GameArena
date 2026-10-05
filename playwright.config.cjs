const { defineConfig, devices } = require('@playwright/test');
const baseURL = process.env.GAMEARENA_UI_BASE_URL || 'http://127.0.0.1:8084';
const parsed = new URL(baseURL);
if (!['127.0.0.1', 'localhost'].includes(parsed.hostname) || parsed.protocol !== 'http:') {
  throw new Error('Browser tests require an isolated loopback preview.');
}
module.exports = defineConfig({
  testDir: './tests/browser',
  use: { baseURL, reducedMotion:'reduce', trace: 'retain-on-failure' },
  projects: [
    {name:'mobile-360', use:{...devices['iPhone SE'], browserName:'webkit', viewport:{width:360,height:800}}},
    {name:'mobile-390', use:{...devices['iPhone 13'], browserName:'webkit', viewport:{width:390,height:844}}},
    {name:'tablet', use:{viewport:{width:768,height:1024}}},
    {name:'desktop', use:{viewport:{width:1440,height:1000}}}
  ]
});
