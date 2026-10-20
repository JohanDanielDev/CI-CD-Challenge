import { expect, test } from "@playwright/test";

test("loads the movie library, filters categories, and searches titles", async ({ page }) => {
  await page.goto("/");

  const cards = page.locator(".movie-card");
  await expect(cards).toHaveCount(36);
  await expect(page.getByText("36 movies", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Comedy" }).click();
  await expect(cards).toHaveCount(12);
  await expect(page.locator('.movie-card:not([data-category="comedy"])')).toHaveCount(0);
  await expect(page.getByText("12 movies", { exact: true })).toBeVisible();

  await page.getByRole("searchbox", { name: "Search movies" }).fill("Superbad");
  await expect(cards).toHaveCount(1);
  await expect(cards.locator(".movie-title")).toHaveText("Superbad");
  await expect(page.getByText("1 movie", { exact: true })).toBeVisible();

  await page.getByRole("searchbox", { name: "Search movies" }).fill("not in the catalog");
  await expect(cards).toHaveCount(0);
  await expect(page.getByText("No movies found")).toBeVisible();
});

test("sends the selected category and preference to the AI guide", async ({ page }) => {
  let requestPayload;
  await page.route("**/api/recommendations", async route => {
    requestPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        category: "thriller",
        recommendation: "1. The Dark Knight (2008) — thriller",
        recommendations: [{ title: "The Dark Knight" }],
      }),
    });
  });

  await page.goto("/");
  await expect(page.locator(".movie-card")).toHaveCount(36);
  await page.getByRole("button", { name: "Thriller" }).click();
  await expect(page.locator(".movie-card")).toHaveCount(12);
  await page.getByRole("textbox", { name: "Describe the kind of movie you want" })
    .fill("A clever mystery with a twist");
  await page.getByRole("button", { name: "Ask Gemma" }).click();

  await expect(page.locator("#aiResult")).toContainText("The Dark Knight");
  expect(requestPayload).toMatchObject({
    category: "thriller",
    preference: "A clever mystery with a twist",
    exclude_titles: [],
  });
});

test("shows AI service errors and lets the user retry", async ({ page }) => {
  await page.route("**/api/recommendations", route => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ error: "The AI guide is unavailable." }),
  }));

  await page.goto("/");
  await expect(page.locator(".movie-card")).toHaveCount(36);
  await page.getByRole("button", { name: "Ask Gemma" }).click();

  await expect(page.locator("#aiResult")).toHaveText("The AI guide is unavailable.");
  await expect(page.getByRole("button", { name: "Ask Gemma" })).toBeEnabled();
});
