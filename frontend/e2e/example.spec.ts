import { test, expect } from '@playwright/test';

test.describe('Example E2E Tests', () => {
  test('has title', async ({ page }) => {
    await page.goto('/');

    // タイトルにAP2が含まれることを確認
    await expect(page.getByTestId('home-title')).toContainText('AP2');
  });

  test('page loads successfully', async ({ page }) => {
    await page.goto('/');

    // ページが正常に読み込まれることを確認
    await expect(page.getByTestId('home-page')).toBeVisible();
  });
});
