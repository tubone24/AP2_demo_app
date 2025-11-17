import { test, expect } from '@playwright/test';

test.describe('Home Page', () => {
  test('should display the home page with navigation links', async ({ page }) => {
    await page.goto('/');

    // ページタイトルの確認
    await expect(page.getByTestId('home-title')).toHaveText('AP2 Demo App v2');

    // サブタイトルの確認
    await expect(page.getByTestId('home-subtitle')).toContainText('Agent Payments Protocol');

    // ナビゲーションリンクの確認
    await expect(page.getByTestId('nav-shopping-chat')).toBeVisible();
    await expect(page.getByTestId('nav-payment-methods')).toBeVisible();
    await expect(page.getByTestId('nav-merchant-dashboard')).toBeVisible();
  });

  test('should navigate to chat page when clicking Shopping Chat link', async ({ page }) => {
    await page.goto('/');

    await page.getByTestId('nav-shopping-chat').click();

    // チャットページに遷移したことを確認
    await expect(page).toHaveURL(/.*\/chat/);
  });

  test('should navigate to payment methods page when clicking payment link', async ({ page }) => {
    await page.goto('/');

    await page.getByTestId('nav-payment-methods').click();

    // 支払い方法ページに遷移したことを確認
    await expect(page).toHaveURL(/.*\/payment-methods/);
  });

  test('should navigate to merchant dashboard when clicking merchant link', async ({ page }) => {
    await page.goto('/');

    await page.getByTestId('nav-merchant-dashboard').click();

    // マーチャントダッシュボードに遷移したことを確認
    await expect(page).toHaveURL(/.*\/merchant/);
  });
});
