const {test, expect} = require('@playwright/test');
test('guest home has responsive navigation and complete hero artwork', async ({page}, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', {level:1})).toContainText('Find your game.');
  await expect.poll(() => page.locator('.ga-hero-artwork').first().evaluate(img => img.naturalWidth)).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.locator('[data-notification-menu]')).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath('home.png'), fullPage:true});
  expect(errors).toEqual([]);
});

test('profile file picker fits after selecting a long filename', async ({page}, testInfo) => {
  await page.goto('/login');
  await page.getByLabel('Email', {exact:false}).fill('preview@example.com');
  await page.getByLabel('Password', {exact:true}).fill('Preview-Only-42!');
  await page.locator('button[type=submit], input[type=submit]').click();
  await page.goto('/profile');
  await page.getByText('Update profile photo', {exact:true}).click();
  await page.locator('#avatar-file').setInputFiles({
    name:'a-very-long-profile-photo-filename-that-must-stay-inside-the-card.png',
    mimeType:'image/png',
    buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6kAAAAABJRU5ErkJggg==','base64')
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.locator('#avatar-file')).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('profile.png'), fullPage:true});
});
